# Phase S-0 実施報告: Drive System(内発的動機の集約層)

**目的:** 既存の測定・検証系の仕組み(Phase RのRC指標、B3の確信度・確認候補、B16の目標整合性フラグ)を、"監視のための数字"としてだけでなく、"シグマリス自身が内的に気にかける動機(Drive)"として読み替える、薄い読み取り専用の集約層を実装する。
**作業ブランチ:** `phase-s0-drive-system`(mainから新規作成)
**範囲:** Drive状態の算出・提供まで。行動への変換(S-1: Executive Gate、S-2: Goal Proposal)は次タスク。

---

## 0. 前提として確認したこと

着手前に指示書が指定した3ファイル(`phase_r_report.md`・`temporal_layer_report.md`・`phase_b_summary.md`)に加え、実際の材料元となる以下のコードを確認した。

- `backend/app/services/active_inquiry.py`(B3): `get_inquiry_question()`が`user_fact_data.get_null_fields()`(未入力プロフィール項目)と`memory_validator.get_confirmation_candidates()`(確信度が低い/矛盾フラグ付き/長期未更新の既存事実)を1つの候補プールに合流させ、会話文脈との関連度でランキングして質問を生成している。
- `backend/app/services/memory_validator.py`の`get_confirmation_candidates()`: 各候補に`confidence`(float)と`confirm_reason`(`low_confidence`/`flagged_stale`/`long_unupdated`のいずれか)を持つ。
- `backend/app/services/goal_alignment.py`(B16): `get_active_goal_alignment_flags()`は応答への提示可否(`_SURFACE_COOLDOWN_DAYS`によるクールダウン)を考慮した関数であり、内的な緊張度の把握には向かない。クールダウンを見ない全件取得は`_get_all_flags_for_context()`(モジュール内プライベート、goal_reference重複排除のコンテキスト生成用に既存)がR-1・R-3で既に転用されている前例がある。
- `backend/app/services/cycle_health_runs_store.py`(Phase R-3): `get_recent_cycle_health_runs(limit=N)`がRC-1〜RC-5の最新実行結果を返す。
- **`backend/app/services/internal_state.py`(既存、Phase Sとは無関係)**: `sigmaris_internal_state`テーブルに、`curiosity`という**別概念**のfloat列が既に存在することを発見した。これは`orchestrator/service.py::_cognitive_layer_bg()`が会話ターンごとに`min(1.0, current + 0.01)`で単調増加させる、B3の実データとは一切連動しないムード的な値である。**本タスクの`CuriosityDrive`とは無関係であり、混同しないよう7章で明記する。**

---

## 1. 3種類のDrive状態、それぞれの算出ロジックと参照データ

3つのDriveはいずれも**新規のI/Oを一切追加せず**、既存の読み取り関数をそのまま呼び出して得られたデータを、シンプルな集計(件数・平均・上限付き線形写像)で`level`(0.0〜1.0)に変換する。**3つのDriveは意図的に1つの数値へ統合していない**(要件の通り)——`DriveState`は`curiosity`/`mastery`/`coherence`の3つの独立したデータクラスをフィールドとして持つのみで、それらを合成する処理はどこにも存在しない。

### 1.1 Curiosity Drive(好奇心)

**参照データ**: `user_fact_data.get_null_fields(jwt)`(未入力のプロフィール項目)+ `memory_validator.get_confirmation_candidates(jwt)`(確信度低下・矛盾フラグ・長期未更新の既存事実)。いずれも**B3が既に使っている関数をそのまま呼ぶだけ**で、新しいクエリ・新しい判定ロジックは一切追加していない。

```
candidate_count = len(null_fields) + len(confirm_candidates)
level = min(1.0, candidate_count / 8)   # 8件で飽和(判断根拠は3.1節)
```

付随情報として、確認候補の`confidence`の平均値(低いほど「気になる度合いが強い」ことを示すが、levelそのものには混ぜ込まず別フィールドとして提供——3つのDrive間だけでなく、Drive内部の合成もできる限り透明に保つ判断)と、`confirm_reason`別の内訳を提供する。

### 1.2 Mastery Drive(改善欲求)

**参照データ**: `cycle_health_runs_store.get_recent_cycle_health_runs(limit=1)`(Phase R-3が保存した直近1件のRC計測結果)。`run_cycle_health()`をライブ再実行することは**しない**——理由は3.2節。

```
gaps = [1 - rc1_eligible_completion_rate, 1 - rc2_score]  # Noneは除外
level = mean(gaps)  # gapsが空ならlevel=None
if rc5_status == "break_detected":
    level = max(level or 0.0, 0.7)  # フロア(判断根拠は3.1節)
```

`has_data=False`(=直近実行が1件も無い)の場合は`level=None`とし、`0.0`(=循環は完璧に健全)と決して混同しない。これはR-2/R-3で確立した「未測定と良好を区別する」設計をそのまま踏襲したものであり、Phase Sで新たに導入した判断ではない。

### 1.3 Coherence Drive(一貫性欲求)

**参照データ**: `goal_alignment._get_all_flags_for_context()`(B16の全アクティブ乖離フラグ、提示クールダウンを考慮しない)+ 直近のRC-4(方策と信念の一致度、`cycle_health_runs_store`経由)。

```
flag_component = min(1.0, active_flag_count / 5)  # 5件で飽和(判断根拠は3.1節)
components = [flag_component] + ([1 - rc4_score] があれば追加)
level = mean(components)
```

Coherence DriveはMastery Driveと異なり、フラグ件数(0件でも「対立が無い」という正当な観測値)が常に存在するため、`level`が`None`になることはない——「未測定」に相当する状態が構造的に存在しないため(フラグ0件を「未測定」として扱う理由がない)。RC-4が未測定(直近実行なし、またはその実行でRC-4自体が評価対象フラグ0件でNoneだった)の場合のみ、`flag_component`単独でlevelを算出する。

---

## 2. 新規実装した部分とその判断根拠

### 2.1 新規テーブル: なし

指示書の指示通り、着手前に「既存データだけで表現できないか」を検討した。結果、**新規テーブルは一切必要なかった**——3つのDriveの材料は全て既存の3系統(B3・Phase R・B16)の読み取り関数から取得でき、いずれも書き込みは行わない。

### 2.2 新規の計算ロジック: `drive_system.py`内の集計関数のみ

以下の3関数(`_compute_curiosity_drive`・`_compute_mastery_drive`・`_compute_coherence_drive`)と、それらをまとめる`get_current_drive_state()`が本タスクで新規に追加した唯一のコードである。いずれも既存データの読み取り+単純な算術(件数・平均・`min`によるキャップ)のみで構成されており、機械学習・新しい判定基準・新しいDB問い合わせパターンは一切導入していない(要件「過剰な設計を避けること」に対応)。

### 2.3 唯一「新規計算」と呼べる要素: 3つの飽和点定数と`break_detected`フロア

`_CURIOSITY_SATURATION_COUNT=8`・`_COHERENCE_SATURATION_COUNT=5`・`_MASTERY_BREAK_FLOOR=0.7`の3つの定数は、この調査時点では実データによる検証ができていない、経験則ベースの暫定値である。判断根拠は`drive_system.py`内のコメントに明記した(要旨: Curiosityは1ターン1問・48時間クールダウンという運用ペースから、Coherenceは乖離フラグ自体が複数証拠を要して初めて1件生成される希少性から、Mastery Floorは「悪化検知という事実自体の重み」から、それぞれ経験的に設定した)。これらは`cycle_health_metrics.py`の`_CYCLE_BREAK_DROP_THRESHOLD`(RC-5)等、このコードベースで既に確立されている「未検証の暫定チューニング定数として明示し、実データ蓄積後に見直す」というパターンをそのまま踏襲している。

### 2.4 永続化・キャッシュを追加しなかった判断根拠

指示書2章の通り、Drive状態は「呼び出しのたびに動的に計算」する設計にした。理由:

- Curiosity: `get_null_fields`/`get_confirmation_candidates`はB3が既に毎ターン相当の頻度で呼んでいる既存の読み取りであり、Drive算出のために新たに重くなるわけではない。
- Mastery/Coherence: `get_recent_cycle_health_runs(limit=1)`は単一行の`SELECT ... ORDER BY run_at DESC LIMIT 1`であり、Phase R自体の実行頻度(週次想定)を考えれば無視できるコスト。
- Coherenceで`get_recent_cycle_health_runs`をMasteryと重複して2回呼んでいる点はやや冗長だが、上記の通り1回あたりのコストが軽微なため、共有化・TTLキャッシュ導入のための複雑化は要件2(新規ロジックは必要最小限に)に照らして見送った——判断根拠として明記する。

---

## 3. 参照インターフェースの設計

### 3.1 シグネチャ: `get_current_drive_state(jwt: str) -> DriveState`

指示書の例示シグネチャは`get_current_drive_state(user_id)`だったが、**`jwt`を受け取る形に変更した**。判断根拠: Curiosity Driveの材料(`get_null_fields`/`get_confirmation_candidates`)は、いずれも`user_fact_items`/`user_fact_profile`へのJWTスコープRLS経由の読み取りしかサポートしておらず(このコードベースの既存関数のシグネチャそのもの、`user_id`だけでは呼び出せない)、`run_eval.py`/`run_cycle_health.py`が一貫して`jwt`を主引数にしているのと同じ理由に基づく。S-1/S-2からの呼び出し時も、既存のオーケストレーター経路が既に保持している`jwt`をそのまま渡せる。

### 3.2 戻り値: `DriveState`(3つの独立したデータクラスを持つ）

```python
@dataclass
class DriveState:
    curiosity: CuriosityDrive
    mastery: MasteryDrive
    coherence: CoherenceDrive
```

`CuriosityDrive`・`MasteryDrive`・`CoherenceDrive`はいずれも`level`(主要な数値)に加え、S-1/S-2が「なぜその値になったか」を追加のLLM呼び出しなしで判断できるよう、内訳フィールド(候補件数・reason別内訳・RC各指標の生値・フラグ件数等)を保持する——単一の`level`だけでは「なぜ高まっているか」が分からず、後続タスクが判断材料を得るために本モジュールへの逆問い合わせや独自の再集計を余儀なくされることを避けるための設計判断。

### 3.3 S-1/S-2が想定される利用形態(設計メモ、本タスクでは未実装)

- S-1(Executive Gate、能動的発話の可否判断)は、`DriveState`の3つの`level`のうちいずれかが高い状態を「今この瞬間、能動的に動く動機がある」根拠として参照する形が自然だと考えられる。
- S-2(Goal Proposal)は、`level`だけでなく`reason_counts`(Curiosity)・`rc5_broke_metrics`(Mastery)・`active_flag_count`(Coherence)といった内訳フィールドを、実際に何を提案すべきかの手がかりとして使うことが想定される。
- どのDriveをどう重み付けし、実際の行動に変換するかは**本タスクのスコープ外**であり、判断・設計は行っていない。

---

## 4. テスト結果

いずれもモック(実DB未接続、`unittest.IsolatedAsyncioTestCase`)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
CuriosityDriveTests (4件)
  PASS: 候補が0件のときlevel=0.0になること
  PASS: 候補数が飽和点(8件)を超えてもlevelが1.0にキャップされること(10件→1.25にならない)
  PASS: 確認候補のconfidence平均・confirm_reason別内訳が正しく集計されること
  PASS: 上流(get_null_fields/get_confirmation_candidates)が例外を投げても、
        Drive算出自体は例外を伝播させず空データに縮退すること

MasteryDriveTests (4件)
  PASS: 直近実行が1件も無い場合、has_data=Falseかつlevel=None(0.0ではない)になること
  PASS: 健全な実行結果(RC-1=0.9, RC-2=0.95)からgapの平均としてlevelが算出されること
  PASS: RC-5がbreak_detectedの場合、個々のgapが小さくてもフロア値(0.7)まで
        levelが引き上げられること
  PASS: 実行は存在するがRC-1/RC-2が共にNone(insufficient_history等)の場合、
        has_data=Trueのままlevel=Noneになること(「実行された」と「測定できた」の区別)

CoherenceDriveTests (3件)
  PASS: フラグ0件・RC-4データなしでlevel=0.0になること(未測定ではなく正当な0)
  PASS: フラグ2件(evidence_count合計5)+RC-4=0.4のとき、
        flag_component(2/5)とrc4_gap(0.6)の平均としてlevelが算出されること
  PASS: フラグ件数が飽和点(5件)を超えてもlevelが1.0にキャップされること

GetCurrentDriveStateIntegrationTests (1件)
  PASS: get_current_drive_state()が3つの独立したDrive dataclassを返し、
        Mastery側にデータが無い状態でも、Curiosity/Coherence(データありの0.0)
        の算出には影響しないこと(Drive間の独立性の直接確認)

12 passed
```

既存の`backend/tests/`(16件)を変更前後で再実行し、リグレッションがないことを確認した。

```
16 passed(変更前)
16 passed(変更後)
```

**実モデルAPI・実DBでの検証は行っていない。** 注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない。本タスクは新規マイグレーションを一切必要としない(既存データの読み取りのみのため)。

---

## 5. 気づいた懸念点・S-1(Executive Gate)に向けた申し送り

1. **`sigmaris_internal_state.curiosity`との名前の衝突リスク(最重要)**: 0章で述べた通り、既存の内部状態テーブルに、本タスクの`CuriosityDrive`とは無関係な、単調増加するムード値としての`curiosity`列が既に存在する。S-1以降の実装者が両者を見比べた際、片方をもう片方の後継・重複と誤解するリスクが高い。**この2つの`curiosity`は統合しないことを推奨する**——`sigmaris_internal_state.curiosity`は会話の"雰囲気"としての性質を持ち、`DriveState.curiosity`はB3の実データに基づく具体的な"未解決事項の量"であり、性質が異なる。将来的にどちらかを廃止・統合するかは、S-1着手前に明示的な設計判断として一度議論する価値がある。
2. **飽和点定数(8・5)とMasteryフロア(0.7)は完全に未検証**: 2.3節の通り、実データが無い状態での経験則にすぎない。運用者が実際にPhase Rの`run_cycle_health.py`・B3の確認候補件数を継続的に観測した上で、これらの定数を早期に見直すことを推奨する。
3. **Coherence Driveのrc4_score取得が、Mastery Driveと同じ`get_recent_cycle_health_runs(limit=1)`を独立して2回呼んでいる**(2.4節)。現状は実害が無いと判断したが、S-1がDrive状態を高頻度(例えば会話ターンごと)に呼び出す設計になった場合は、再考の余地がある。
4. **`level`の意味論はDriveごとに異なる**: MasteryとCoherenceの`level`は「理想からどれだけ乖離しているか(gap)」の平均として設計されている一方、Curiosityの`level`は「未解決の候補がどれだけ溜まっているか(count)」であり、両者は同じ0.0〜1.0スケールでも意味が異なる合成のされ方をしている。3つのDriveを比較・重み付けする際は、この非対称性を踏まえる必要がある(要件通り1つの数値に統合していないため実害は無いが、S-1が3つを比較する設計にする場合は要注意)。
5. **Coherence Driveのフラグ取得(`_get_all_flags_for_context`)はモジュール内プライベート関数の直接importである**——R-1・R-3が既に同じ判断(`experience_layer._CONSOLIDATION_SCAN_WINDOW`等の直接import)を行っており、本タスクもその前例を踏襲したが、こうした「プライベート関数の他モジュールからの再利用」が3回目になった。もし今後さらに増える場合、`goal_alignment.py`側で正式に公開関数として昇格させることを検討する価値がある。
6. **B3の`get_null_fields`は`user_fact_profile`が未作成の場合、固定のプロフィールフィールド全件(氏名・生年月日等)を返す設計になっている**(`user_fact_data.py`)。新規ユーザーの初回利用時、Curiosity Driveの`candidate_count`が初手から高い値になりうる——これは「シグマリスがまだ何も知らない」という状況として自然だが、S-1が「Curiosityが高い=積極的に質問すべき」という単純な変換をする場合、初回利用時に質問攻めになるリスクがある点は留意が必要。
