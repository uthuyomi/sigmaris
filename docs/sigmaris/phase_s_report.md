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

---

# Phase S-1 実施報告: Executive Gate + curiosity名前衝突の整理

**作業ブランチ:** `phase-s1-executive-gate`(mainから新規作成)
**範囲:** curiosity名前衝突の整理、およびExecutive Gate(いつ話しかけていいかの判定ロジック)の実装。実際の発話生成(S-2: Goal Proposal)は次タスク。

---

## 6. curiosity名前衝突の整理

### 6.1 実際の用途・参照箇所の確認結果

着手前に、`curiosity`という語を持つ既存箇所を全文検索し、**S-0報告書が想定していた「2つの衝突」ではなく、実際には3つの独立した`curiosity`概念が存在すること**を確認した。

| # | 実体 | 性質 | 主な参照箇所 |
|---|---|---|---|
| 1 | `sigmaris_internal_state.curiosity`(既存) | 会話ターンごとに`min(1.0, +0.01)`で単調増加するムード的float値。B3の実データとは一切連動しない | `internal_state.py`(`_DEFAULTS`・`update_internal_state`・`snapshot`)、`orchestrator/service.py::_cognitive_layer_bg()`(唯一の書き込み元) |
| 2 | `curiosity_engine.py` / `sigmaris_curiosity_queue`(既存、S-0調査時には未発見) | 好奇心駆動の**研究クエリのキュー**(Web検索対象の管理)。人格・自己認識の柱として設計された、全く別の機能領域 | `routes/agent.py`(`GET /curiosity/queue`)、`proactive/scheduler.py`(`_curiosity_search`ジョブ、日次6:15)、`research_agent.py` |
| 3 | `drive_system.CuriosityDrive`(S-0で新設) | B3の未入力プロフィール項目・低確信度事実の件数から算出する、Drive System独自の値 | `drive_system.py`のみ |

**3の存在は、1・2いずれとも無関係かつ独立している。** S-0報告書は1のみを名前衝突として指摘していたが、実際には2も同じ語を含んでおり、「curiosity」という語だけでは3つのうちどれを指しているか文脈なしには判別できない状態だったことが、本タスクの調査で新たに判明した。

### 6.2 選択した対応方針とその根拠

**S-0側の`CuriosityDrive`を`KnowledgeGapDrive`に、`DriveState.curiosity`フィールドを`DriveState.knowledge_gap`に改称した。** `sigmaris_internal_state.curiosity`の列名・変数名、および`curiosity_engine.py`の関数名・テーブル名はいずれも変更していない。

判断根拠:

1. **依頼書の明示的な指示**により、`sigmaris_internal_state.curiosity`の列名・変数名は変更対象外。
2. **`curiosity_engine.py`の改名は本タスクのスコープ外と判断した。** 依頼書が名前衝突の整理対象として明示していたのは`sigmaris_internal_state.curiosity`のみであり、6.1節で新たに発見した`curiosity_engine.py`との衝突は、依頼書が想定していなかった追加の発見である。この場を借りて改名まで踏み込むと、依頼書が定めた本タスクの範囲(「curiosity名前衝突の整理」の対象は明示された1件)を超えるため、**発見事実の報告のみに留め、対応は別タスクの判断に委ねる**(依頼書「両者を統合すべきという結論に至った場合は、実装せず分析結果のみ報告」という指示の精神を、"統合"だけでなく"追加の衝突発見"にも適用した)。
3. **`CuriosityDrive`(S-0で1日前に新設されたばかりで、依頼書の时点で唯一の呼び出し元であるテスト以外に外部消費者が存在しない)を改称する方が、既存の2つ(1・2、いずれもより長く存在し、他モジュールから広く参照されている)を触るより低リスクである。** 特に1は`orchestrator/service.py`の応答経路(fire-and-forgetとはいえ毎ターン実行される`_cognitive_layer_bg()`)から書き込まれており、2はスケジューラジョブ・APIルート・research_agent.pyの3箇所から参照される、この時点で最も改名コストが高い候補だった。
4. **改称先を"KnowledgeGapDrive"/"knowledge_gap"にした根拠**: このDriveが実際に算出している内容(未入力のプロフィール項目+確信度の低い/古い事実の件数)を最も直接的に表す語であり、かつ"curiosity"という語を一切含まないため、将来同じ語で検索しても1・2とは明確に区別できる。依頼書の例示(「`CuriosityDrive`はそのままクラス名として残しつつ、コメントで違いを明記する」)ではなく実際の改称を選んだ理由は、コメントによる注記だけでは、3つの`curiosity`概念のうち少なくとも2つ(1・3)が今後も同じ語のまま並存し続け、grep等の機械的な発見に頼った際に誤って混同するリスクが残ると判断したため。

### 6.3 実施した変更

`backend/app/services/drive_system.py`内で完結する改称のみ(他ファイルへの影響なし——`get_current_drive_state()`の外部呼び出し元は本タスク時点でまだ存在しないため、破壊的変更の影響範囲はゼロ)。

- クラス`CuriosityDrive` → `KnowledgeGapDrive`
- `DriveState.curiosity`(フィールド) → `DriveState.knowledge_gap`
- 内部関数`_compute_curiosity_drive()` → `_compute_knowledge_gap_drive()`
- 定数`_CURIOSITY_SATURATION_COUNT` → `_KNOWLEDGE_GAP_SATURATION_COUNT`
- モジュール冒頭のコメント、および`KnowledgeGapDrive`のdocstringに、6.1・6.2節の経緯(何から改称したか、既存の2つの`curiosity`概念との関係)を明記した——将来のコード読者がgitログを遡らなくても経緯を追えるようにするため。

`mastery`/`coherence`の命名はそのまま維持した(衝突が無いため変更の必要がない)。この結果、`DriveState`の3フィールド名が`knowledge_gap`/`mastery`/`coherence`という非対称な形(1つだけ2語)になったが、6.2節の理由により意図的な選択であることを明記する。

---

## 7. Executive Gateの判定ロジック詳細

`backend/app/services/executive_gate.py`(新規)に`evaluate_executive_gate(jwt, *, is_urgent=False, now=None) -> ExecutiveGateResult`を実装した。

### 7.1 判定の全体フロー

```
1. 深夜早朝(23:00〜07:00、settings.sigmaris_timezone基準)か?
   → is_urgent=Falseなら、ここで即座に blocked_by="quiet_hours" で却下
     (Drive Stateは取得しない)
2. 直近3時間以内に自発的な話しかけを行っていたか?
   → 行っていれば blocked_by="cooldown" で却下(Drive Stateは取得しない)
3. drive_system.get_current_drive_state()を取得し、
   knowledge_gap/mastery/coherenceいずれかのlevelが0.6以上か?
   → 1件でもあれば may_speak=True、無ければ blocked_by="no_drive_above_threshold"
```

絶対制約(1・2)のいずれかで却下される場合、**Drive State自体を取得しない**設計にした(`drive_state=None`のまま返す)。判断根拠: 絶対制約は「参照するまでもなく結果が決まっている」ケースであり、そこでDrive Stateを取得するのは無駄なI/O(B3の候補取得・Phase R実行結果取得・B16フラグ取得、計4系統の読み取り)を発生させるだけである。テストで、この短絡が実際に機能していること(絶対制約で却下される場合に`get_current_drive_state`が一切呼ばれないこと)を直接確認した(8章参照)。

### 7.2 絶対的制約1: 深夜早朝(quiet hours)

- **時間帯**: 23時〜7時(またぎ)、依頼書の目安通り。既存の設定に、これに相当する値は見つからなかった(`settings`クラスに`quiet_hour`系の設定は存在しない)ため、依頼書のフォールバック値をそのまま採用した。
- **判断根拠として明記**: この時間帯は、既存の朝ブリーフィング(8:00開始)・夕方チェックイン(22:00開始)という2つの固定スケジュール(`proactive/scheduler.py`)の外側に、それぞれ1時間の余裕を持って収まっている。既存のスケジュールが暗黙に前提としていた「活動時間帯」(おおよそ7時台〜23時前後)と矛盾しない値であることを確認した。
- **`is_urgent`引数**: 依頼書の「緊急以外の」という文言に対応するバイパス機構として用意した。ただし、**本タスク時点で`is_urgent=True`を渡す呼び出し元は存在しない**(「何が緊急か」の判定自体はS-1のスコープ外、S-2以降の課題)。`is_urgent=True`は深夜早朝の制約のみをバイパスし、次節のクールダウンはバイパスしない——「緊急なら深夜でも起こしてよい」と「緊急なら何度でも連投してよい」は別の性質の判断であり、後者まで緩めることは依頼書が要求していないため、安全側に倒した判断根拠を明記する。

### 7.3 絶対的制約2: 連続話しかけ防止(クールダウン)

- **参照データ**: `agent_invocation_audit_logs`から、`caller_agent_id`が`"proactive-scheduler:"`で始まる直近1件の`created_at`を取得する。この判定基準は新規のものではなく、`orchestrator/service.py::_is_proactive_call()`が既に使っている、Temporal Layer Step2で確立済みのプレフィックス規約をそのまま踏襲した(依頼書の「Temporal Layerの`last_mentioned_at`の仕組みを参考にすること」に対応する形として、**新しい記録テーブル・記録経路を追加せず、既存の監査ログを読むだけ**という設計を選んだ——`last_mentioned_at`自体は個々の事実単位の粒度であり、会話全体の頻度を見る本用途にはそのまま転用できないため、"仕組みの考え方"を踏襲しつつ、実際のデータソースは既存の監査ログにした、という判断根拠)。
- **クールダウン期間**: 3時間。B3の48時間(フィールド単位の再確認クールダウン)・B16の14日間(同一乖離フラグの再提示クールダウン)のいずれとも異なる、「同日内での連投を避ける」ことを主眼とした値。**未検証の暫定値であることを明記する**(9章参照)。
- 直近の自発的接触が1件も無い場合(新規稼働直後等)は、クールダウン非該当として扱う(`cooldown_active=False`)。

### 7.4 Drive State参照の閾値

各Driveの`level`が**0.6以上**であれば、そのDriveが「話しかけてよい」根拠として基準を満たしたとみなす。3つのDriveのうち1つでも基準を満たせば`may_speak=True`（`triggering_drives`に該当するDrive名を全て列挙する——複数のDriveが同時に閾値を超えることもありうる)。

0.6という値の判断根拠: 中間点(0.5)よりやや高く、`MasteryDrive`の`break_detected`フロア(0.7、S-0で導入済み)よりは低い水準を意図した。「明確に高まっている」が「緊急事態ではない」という中間的な強度を表す値として選んだが、**これも未検証の暫定値**である(9章参照)。

`level=None`(Mastery Driveが未計測の場合)は、`None >= 0.6`という比較を行わずに除外している(Pythonでは`None >= 0.6`は`TypeError`になるため、`level is not None`を先に確認する実装にした——テストで直接確認済み、8章参照)。

---

## 8. テスト結果

いずれもモック(実DB未接続、`unittest`)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
QuietHoursPureFunctionTests (1件)
  PASS: _is_quiet_hours()の境界値(22時=false, 23時=true, 0時=true,
        6時=true, 7時=false, 14時=false)が全て正しいこと

ExecutiveGateQuietHoursTests (2件)
  PASS: 深夜早朝(JST 02:00)はDrive Stateを一切取得せずに却下されること
        (_get_last_proactive_contact_at・get_current_drive_stateの
        いずれも呼ばれないことを直接確認——7.1節の短絡設計の検証)
  PASS: is_urgent=Trueの場合、深夜早朝でもblocked_by≠"quiet_hours"となり、
        Drive State次第でmay_speak=Trueになりうること

ExecutiveGateCooldownTests (3件)
  PASS: 直近1時間以内に自発的接触があった場合、クールダウンで却下され
        Drive Stateが取得されないこと
  PASS: クールダウン期間(3時間)を過ぎていれば却下されないこと
  PASS: 直近の接触記録が1件も無い場合はクールダウン非該当として扱われること

ExecutiveGateDriveThresholdTests (4件)
  PASS: いずれかのDriveが閾値(0.6)を超えている場合にmay_speak=True、
        triggering_drivesに正しく列挙されること
  PASS: 全てのDriveが閾値未満のときmay_speak=False、
        blocked_by="no_drive_above_threshold"になること
  PASS: MasteryDriveのlevel=None(未計測)が、閾値判定でエラーにも
        誤ったTrue判定にもならないこと
  PASS: 複数のDriveが同時に閾値を超えた場合、両方がtriggering_drivesに
        列挙されること

10 passed
```

S-0のscratchテスト(12件、`KnowledgeGapDrive`への改称を反映して更新した上で)を再実行し、**改称後も算出ロジック自体には変化がないこと**を確認した。

```
12 passed(S-0、改称後の名前で再実行)
```

既存の`backend/tests/`(16件)を変更前後で再実行し、リグレッションがないことを確認した。

```
16 passed(変更前)
16 passed(変更後)
16 + 12 + 10 = 38 passed(backend/tests/ + S-0 scratch + S-1 scratch、合算実行)
```

**実モデルAPI・実DBでの検証は行っていない。** 注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない。本タスクは新規マイグレーションを必要としない(既存テーブルの読み取りのみのため)。

---

## 9. 気づいた懸念点・S-2(Goal Proposal)に向けた申し送り

1. **`curiosity_engine.py`(研究クエリキュー)との3つ目の名前衝突が残っている(6.1節)。** 本タスクでは対応範囲外としたが、`sigmaris_internal_state.curiosity`・`curiosity_engine.py`・(改称後の)`KnowledgeGapDrive`という3つの独立した概念が同じプロジェクト内に存在する状態は、依然として将来の混乱リスクを抱えている。特に`curiosity_engine.py`はPhase Sの「人格・自己認識」という設計思想と概念的に近く、将来Phase Sの一部として再統合・再設計される可能性もゼロではない——S-2以降でこの3者の関係を一度整理することを推奨する。
2. **Executive Gateの3つの定数(クールダウン3時間・閾値0.6・quiet hours 23-7時)は、いずれも実データに基づかない暫定値である。** 特にクールダウンと閾値は相互に影響し合う(閾値を下げれば発火しやすくなるが、クールダウンがある限り連投は防がれる、等)ため、片方だけを個別にチューニングすると意図しない挙動になりうる。実運用開始後、両方をセットで見直すことを推奨する。
3. **`is_urgent`引数は用意したが、呼び出し元(何が緊急かを判定するロジック)が存在しない。** S-2(Goal Proposal)が実際に発話内容を生成する段階で、生成された提案内容自体の緊急性を判定し、この引数に渡す設計になると想定されるが、その判定ロジックの設計は本タスクの範囲外であり、着手していない。
4. **クールダウンの起点は「直近の自発的接触」であり、朝ブリーフィング・夕方チェックインという既存の固定スケジュール発話も対象に含まれる。** つまり、朝8:00のブリーフィング直後の3時間(〜11:00)は、たとえDrive Stateが閾値を超えていても、Executive Gate単体では新たな自発的な話しかけが却下される。これは意図した設計(「固定スケジュールの発話も"接触"の一種としてカウントすべき」という解釈)だが、S-2が「既存の3つの固定ブリーフィングとは別枠で、Drive由来の提案には別のクールダウンを設けたい」という設計にしたい場合は、`caller_agent_id`のプレフィックスをさらに細分化する(例: `"proactive-scheduler:drive-triggered:"`のような専用プレフィックス)必要が生じる可能性がある。
5. **Executive Gateは判定結果を返すのみで、実際にどう「話しかける」か(通知・次回チャット冒頭への差し込み等)には一切関与しない。** S-2がこの`ExecutiveGateResult`をどう消費するか(例えば`may_speak=True`をPushover通知のトリガーにする、次回チャット開始時のプロアクティブな一言に使う等)は、本タスクでは一切設計していない。
6. **`evaluate_executive_gate()`は呼び出しのたびに動的計算する設計(Drive Systemと同じ方針)であり、スケジューラからの定期呼び出しは本タスクでは配線していない。** S-2が実際にこれを「いつ呼ぶか」(例えば`proactive/scheduler.py`に新規ジョブとして追加するのか、既存のどこかのジョブに相乗りするのか)を設計する必要がある。

---

# curiosity概念の完全整理 実施報告

**作業ブランチ:** `curiosity-glossary-cleanup`(mainから新規作成)
**範囲:** 3つの`curiosity`概念の役割の再確認、統合可能性の検討(設計方針のみ)、用語集の作成、既存コードへの注釈追加(機能変更なし)。

---

## 10. 3つの概念それぞれの役割の再確認結果

S-1完了時点では「2つの衝突」として認識されていたが、本タスクの調査で改めて全文検索・各参照元のコードを直接確認した結果、以下が判明した。詳細は新設した`docs/sigmaris/glossary_curiosity.md`にまとめたため、ここでは要点のみ記す。

### 10.1 curiosity mood(`sigmaris_internal_state.curiosity`)

- 唯一の書き込み元は`orchestrator/service.py::_cognitive_layer_bg()`。会話ターンごとに無条件で`+0.01`(上限1.0)——実データ(B3の候補件数等)とは一切連動しない。
- 読み取り箇所は3つ確認できた: `snapshot()`(自己参照ビュー)、`decision_log.py`の決定検出時に`sigmaris_decision_log.internal_state_snapshot`へそのまま埋め込む(監査目的)、`GET /agent/state`(外部エージェント向けデバッグ endpoint)。
- **新規の発見**: `get_intervention_level_from_state()`(介入レベル算出、`urgency`・`concern`のみ参照)を含め、調査した範囲でこの値を条件分岐・スコアリングに使っている箇所は1つも見つからなかった。**つまりこの値は現状、書き込まれ続けるだけで、シグマリスのいかなる挙動にも影響しない。**

### 10.2 curiosity research queue(`curiosity_engine.py` / `sigmaris_curiosity_queue`)

- 実際に稼働している参照元は3ファイル4箇所: `research_agent.py`(日次トレンド調査でLOW判定の興味深い項目を自動enqueue)、`proactive/scheduler.py`の2ジョブ(`_curiosity_search`日次6:15=pendingクエリの実行、`_self_interest_queries`日曜5:30=人格憲章Article8の関心軸からクエリ生成)、`routes/agent.py::GET /curiosity/queue`(外部エージェント向け読み取り)。
- 対象は一貫して**外部Web情報源**(HackerNews・arXiv、`research_agent.run_research_for_query()`経由)であり、ユーザー本人への質問とは無関係。
- **新規の発見**: `generate_curiosity_queries()`(232行)という関数が、上記4箇所のいずれからも呼ばれていないデッドコードであることを確認した。このプロンプトは「直近の未解決経験」「古くなった可能性がある事実」を入力として要求する設計になっており、B3/KnowledgeGapDriveが扱うデータと概念的に極めて近い——**まさに依頼書2章が示唆した「同じ概念の異なる実装段階」の具体的な物証**であり、11章の統合可能性の検討で扱う。

### 10.3 Knowledge-Gap Drive(`drive_system.py::KnowledgeGapDrive`)

- `docs/sigmaris/phase_s_report.md`のS-0・S-1セクションの記載を再確認した。B3(`get_null_fields`/`get_confirmation_candidates`)の実データから算出し、S-1(Executive Gate、実装済み)が「自発的に話しかけてよいか」の判定材料として使っている。想定される次の消費者はS-2(Goal Proposal、未着手)。
- 対象は一貫して**ユーザーとの関係**(まだ知らない/確認したいプロフィール・事実)であり、外部Web情報源の検索とは無関係。

---

## 11. 統合可能性の検討結果

### 11.1 結論: 3つとも、現時点では別概念として明確に区別された名前で共存させるべき

いずれのペアも、**対象領域(自分の内面 / 外部世界 / ユーザーとの関係)が異なる**ため、無理に1つに統合すると、それぞれが持っていた明確な意味が失われると判断した。

- **curiosity mood ⇔ curiosity research queue**: 前者は挙動に影響しない抽象的なムード値、後者は具体的な検索クエリという全く異なる粒度・対象であり、統合の余地は見出せなかった。
- **curiosity mood ⇔ Knowledge-Gap Drive**: 前者はB3データと無関係な機械的増加値、後者はB3データそのものの集約であり、対象が異なる(前者はシグマリス自身の"雰囲気"、後者はユーザーについての知識ギャップ)。統合すると「ムードなのか実データなのか」が曖昧になるため、統合すべきではない。
- **curiosity research queue ⇔ Knowledge-Gap Drive**: 10.2節で述べた通り、`generate_curiosity_queries()`というデッドコードが、まさにこの2つを橋渡しする設計として過去に存在していたことが分かった。**この2つだけは、部分的な統合(片方向のデータ供給)の実質的な根拠がある。**

### 11.2 curiosity research queueとKnowledge-Gap Driveの部分統合案(設計方針のみ、実装は行わない)

**推奨する方向性**: 完全な統合(2つを1つのテーブル・1つのモジュールにする)ではなく、**Knowledge-Gap Driveの候補データの一部を、curiosity research queueへの新規クエリのソースとして流し込む**、片方向のデータ供給パイプラインとして設計するのが妥当と考える。判断根拠:

1. **対象データの重なりは部分的でしかない。** B3の`get_null_fields()`(未入力のプロフィール項目、例:生年月日・住所)は性質上、外部のWeb検索では調べようがない——これは「ユーザー本人に聞くしかない」情報であり、curiosity research queueの対象にはなり得ない。一方`get_confirmation_candidates()`の一部(例えば`lifestyle`・`preferences`カテゴリの、長期未更新の趣味・関心に関する事実)は、「最近もその関心は続いているか」を確認する前段階として、関連する外部トレンドを調べることに意味がありうる。**つまり統合すべきは「B3の全データ」ではなく、その一部に限られる。**
2. **既存の設計(デッドコード`generate_curiosity_queries()`)が、まさにこの部分統合を意図していたと解釈できる。** プロンプトの入力(「古くなった可能性がある事実」)は、`get_confirmation_candidates()`の`confirm_reason="flagged_stale"`/`"long_unupdated"`の候補と直接対応させられる。
3. **実装イメージ(あくまで設計メモ、コードは書いていない)**: `KnowledgeGapDrive`算出時に取得済みの`confirm_candidates`(現状は件数・平均confidence・reason内訳のみを保持している)のうち、外部調査に意味がありそうなカテゴリ(例: `lifestyle`/`preferences`/`goals`)のものを、週次バッチ(既存の`_self_interest_queries`ジョブに相乗りする、または新規ジョブとして追加)で`generate_curiosity_queries()`(デッドコードの復活)または`enqueue_curiosity()`へ直接渡す、という形が考えられる。
4. **本タスクでは実装しない。** 依頼書の指示通り、影響範囲の大きい既存コード(`curiosity_engine.py`は3箇所の稼働中ジョブから参照される)への変更は、独立したタスクとして「どのカテゴリを対象にするか」「頻度をどうするか」「B3側の候補データをどう拡張するか(現状KnowledgeGapDriveは集約後のcountしか保持しておらず、個々の候補の`category`は保持していない——この統合を行うにはdrive_system.py側にも小さな拡張が必要になる)」を慎重に設計すべきと判断する。

---

## 12. 用語集ドキュメントの内容

`docs/sigmaris/glossary_curiosity.md`を新規作成した。主な構成:

1. 3つの概念の一覧表(正式名称・実体・状態)
2. それぞれの詳細(何を表すか・書き込み/参照元・新規の発見事項)
3. 3つの関係性の比較表(対象・データの性質・実データとの連動・現在の挙動への影響・導入時期)
4. 今後の用語使用ルールの提案(3点、13章で言及)

内容は10章・11章で述べた調査結果・統合検討結果をそのまま反映しており、重複を避けるためここでは全文を転記しない(原文参照)。

---

## 13. コメント・docstringに追加した注釈の内容(機能変更なし)

以下3ファイルに、**処理ロジックには一切触れず**、モジュール冒頭コメントのみを追加した。

1. **`internal_state.py`**: モジュール冒頭に、`curiosity`列が他の2概念(curiosity research queue・Knowledge-Gap Drive)と無関係であることを明記する5行のコメントを追加。
2. **`curiosity_engine.py`**: モジュール冒頭に、同様の無関係性の説明に加え、`generate_curiosity_queries()`がデッドコードであること、および11章で述べた将来の統合候補である旨を明記する9行のコメントを追加。
3. **`drive_system.py`**: S-1で追加済みだった衝突注記に、本ドキュメント(`glossary_curiosity.md`)への参照を1行追加。

いずれもコメント行の追加のみであり、実行時の挙動には一切影響しない。既存テスト(`backend/tests/`16件)を変更前後で再実行し、全て変化なくPASSすることを確認した。

```
16 passed(変更前)
16 passed(変更後)
```

**用語集ルール自体の「ルール化」(今後のタスク指示書がこのドキュメントを参照する運用)は、ドキュメント上の提案(12章・グロッサリ末尾)に留めた** — 依頼書もこれを「提案する」という表現に留めており、実際にタスク指示書の作成プロセスへ組み込む権限・仕組みは本タスクの範囲外であるため。

---

## 14. 気づいた懸念点・S-2以降で対応すべき統合作業の優先度

1. **【新規発見、優先度: 低〜中】curiosity moodが挙動に一切影響しない"生きた廃棄物"になっている(10.1節)。** これは名前衝突とは独立した、既存機能そのものの懸念点である。2つの選択肢が考えられる: (a) 将来、`get_intervention_level_from_state()`や応答生成のいずれかにこの値を実際に組み込む、(b) 使われる見込みが無いまま残すくらいなら、書き込み自体を止める(`_cognitive_layer_bg()`の`update_internal_state(curiosity=...)`呼び出しを削除する)。**いずれも本タスクのスコープ外であり実装していない**——依頼書が「既存の稼働中コードの機能を変更しない」ことを明示的に求めているため。次の独立したタスクとして、この値の要否を一度議論することを推奨する(優先度は中——実害は無いが、Phase Sの「内発的動機」という設計思想との整合性を考えると、放置し続けるほど"死んだムード値"と"生きたDrive"の混同リスクが増す)。
2. **【11章、優先度: 中】curiosity research queueとKnowledge-Gap Driveの部分統合(デッドコード`generate_curiosity_queries()`の復活)は、実装コストが小さくない見込みである。** `drive_system.py`側で個々の候補の`category`を保持する拡張、`curiosity_engine.py`側で新しい呼び出し経路を追加、対象カテゴリの選定基準の設計、と複数箇所にまたがる。S-2(Goal Proposal)の設計が固まった段階で、Goal Proposalが「ユーザーへの質問」と「外部調査」のどちらの手段を選ぶべきかという、より大きな設計判断の一部として検討するのが筋が良いと考える——単独の小タスクとして先に着手するより、S-2の設計と合わせて評価すべき。
3. **【優先度: 低】`glossary_curiosity.md`の「curiosity moodの導入時期」は本調査では特定できなかった。** git blame等での厳密な調査は本タスクのスコープ外としたため、「詳細な導入時期は本調査未特定」と正直に記載した。必要であれば別途調査可能。
4. **【運用上の申し送り】今後、「curiosity」という語を含むタスク指示書を作成する際は、依頼書冒頭の「着手前に確認すること」に`docs/sigmaris/glossary_curiosity.md`を含めることを強く推奨する。** 本タスク自体がその運用ルールの必要性を証明する事例(S-0が2つと誤認していた衝突が、実際には3つだった)であり、これが徹底されないと同種の後追い調査が繰り返される可能性が高い。

---

# Phase S-2 実施報告: Goal Proposal & Autotelic Loop(自己目標生成)

**作業ブランチ:** `phase-s2-goal-proposal`(mainから新規作成)
**範囲:** S-1のExecutive Gateが「話しかけてよい」と判定した際に、実際に何をするか(行動)を決定・実行する層の実装。Phase D〜H(自己改良システム本体)への接続は行わない。

---

## 15. 各Driveに対応する行動の実装詳細

`backend/app/services/goal_proposal.py`(新規)に`propose_and_act(jwt, gate_result) -> GoalProposalResult | None`を実装した。3つのDriveそれぞれに対応する行動関数(`_act_on_coherence`・`_act_on_mastery`・`_act_on_knowledge_gap`)を持ち、いずれも**新しい検索・生成ロジックを一切追加せず、既存の関数を呼び出すだけ**で構成されている。

### 15.1 Coherence Drive由来の行動

`goal_alignment.get_active_goal_alignment_flags(limit=1)`(B16、既存)を呼び、提示クールダウンを考慮した上で「今まさに言及してよい」フラグが存在するかを確認する。存在すれば、その内容を人間可読な文章にまとめてExperienceとして記録する。

**判断根拠として明記する重要な設計判断**: B16のDB状態(`last_surfaced_at`)には一切書き込まない。`last_surfaced_at`は本来、フラグの内容が実際にユーザーへの応答に注入された時点(`orchestrator/service.py`の応答経路、`mark_pending_surfaced()`→`flush_pending_surfaced_flags()`)で更新されるべきものである。Goal Proposalは会話ターンの外側(Executive Gateが独立に評価される想定の文脈)で実行されるため、ここで`last_surfaced_at`を更新してしまうと、実際にはまだ何も話していないのに「提示済み」という誤った状態になり、本来ユーザーに届くはずだった次の自然な会話でのB16の言及が、14日間のクールダウンによって不当に抑制されてしまう。依頼書の「B16の既存の提示ロジックをトリガーする役割にとどめてよい」を、**新しい書き込みを一切追加しない、読み取りのみの確認**として解釈した。

### 15.2 Mastery Drive由来の行動

RC-1(`rc1_eligible_completion_rate`)・RC-2(`rc2_score`)・RC-5(`rc5_status`/`rc5_broke_metrics`)の生値から、悪化している指標だけを拾い上げ、決定的なルールで日本語の文章を組み立てる(RC-1<0.8なら1文、RC-2<0.8ならもう1文、RC-5がbreak_detectedならさらに1文、を連結するのみ)。

**判断根拠(LLM呼び出しをしない理由)**: 依頼書が「何を改善すべきかを言語化するところまで」と明示的にスコープを絞っており、Phase D(自己改良システム本体)への接続はまだ存在しない。既存のRC値を機械的に文章へ組み立てるだけであれば、新しいLLM呼び出し・プロンプト設計を追加せずに要件を満たせると判断した——依頼書の「新しい検索ロジックを追加しない」という制約の精神を、LLM呼び出しの追加にも拡大解釈して適用した。

### 15.3 Knowledge-Gap Drive由来の行動

**既存の`curiosity_engine.generate_curiosity_queries()`(curiosity整理タスクで発見したデッドコード)を、実際に呼び出し可能な状態にして使う。** この関数はプロンプトの入力として`facts_summary`・`unresolved`・`stale_facts`の3つの文字列を要求するが、いずれも既存の関数からそのまま組み立てられることを確認した。

| プロンプト入力 | 対応するデータ源 | 使用した既存関数 |
|---|---|---|
| `stale_facts`(古くなった可能性がある事実) | B3、KnowledgeGapDriveの確認候補 | `KnowledgeGapDrive.confirm_candidates`(本タスクで追加、16章参照) |
| `unresolved`(直近の未解決経験) | B2、`experience_type="unresolved"`のExperience | `experience_layer.get_recent_experiences(experience_type="unresolved")` |
| `facts_summary`(ユーザー事実サマリー) | B1、アクティブな事実一覧 | `user_fact_data.build_facts_context()` + `get_fact_items()` |

`generate_curiosity_queries()`自体は内部で`enqueue_curiosity()`を呼び、`sigmaris_curiosity_queue`への追加まで完結させる(既存の関数の挙動をそのまま活用、変更していない)。

**判断根拠(ここで検索を同期実行しない理由)**: 依頼書「curiosity_engine.pyの外部Web検索の仕組みは、そのまま活用してよい。新しい検索ロジックを追加しないこと」に従い、"行動"の内容を「意味のある調査クエリをキューへ追加すること」までとした。実際のHackerNews/arXiv検索(`research_agent.run_research_for_query()`)は、既存の日次6:15バッチが引き続き担当する——Executive Gateがトリガーする経路に、重い同期的な外部HTTP呼び出しを新規に持ち込まないための判断である。

---

## 16. `generate_curiosity_queries()`との統合方法(既存資産の拡張点)

`generate_curiosity_queries()`自体、および`curiosity_engine.py`の他の関数・呼び出し元(`research_agent.py`・`proactive/scheduler.py`の2ジョブ・`routes/agent.py`)には**一切変更を加えていない**。

唯一の拡張は`drive_system.py`側: `KnowledgeGapDrive`に`confirm_candidates: list[dict[str, Any]] = field(default_factory=list)`(デフォルト空リストの後方互換フィールド)を追加し、`_compute_knowledge_gap_drive()`が`get_confirmation_candidates()`から取得した生のリストを、集約(件数・平均confidence・reason内訳)だけでなく、そのままこのフィールドにも保持するようにした。これは`glossary_curiosity.md`11.2節が事前に「この統合を行うにはdrive_system.py側にも小さな拡張が必要になる」と予告していた通りの変更であり、既存フィールドの削除・変更は一切行っていない(デフォルト値ありの新規フィールド追加のみ、既存の呼び出し元・テストのコンストラクタ呼び出しへの影響はゼロ——実際にS-0/S-1のscratchテストが変更なしでそのままPASSすることを確認した、19章参照)。

---

## 17. 優先順位付けロジックとその根拠(Autotelic Loop)

`_DRIVE_PRIORITY = ("coherence", "mastery", "knowledge_gap")`を採用した。依頼書が例示した「Coherence > Mastery > Curiosity(目標との矛盾解消を最優先)」をそのまま採用した判断根拠:

1. **Coherence(目標整合性)**: 海星さん本人が明言した長期目標との矛盾は、当事者への影響が最も直接的である。
2. **Mastery(循環健全性)**: シグマリス自身の内部循環の健全性に関わるが、ユーザーへの直接的な影響は間接的(記憶精度の劣化等を通じて、いずれ体感される)。
3. **Knowledge-Gap(知識ギャップ)**: 3つの中で最も探索的・非緊急——「まだ知らないことがある」状態自体は、直ちに対処が必要な問題ではない。

### フォールバック機構(判断根拠)

優先度が高いDriveが閾値を超えていても、その場に**具体的に提案できる内容が無い場合**(例: Coherenceが閾値を超えていても現在提示可能なフラグが1件もない、Masteryが閾値を超えていても個々のRC値が僅かにしか悪化していない等)は、次点のDriveへフォールバックする設計にした。「優先度が高いDriveが該当したのに、中身が空だったので今回は何もしない」と短絡させず、実際に行動可能なDriveが見つかるまで`triggering_drives`を辿る。全てのtriggering_drivesで行動が生成できなければ`None`を返す——これ自体は異常ではなく、「今は特に自発的に行うべきことがない」という正当な状態として扱う(R-2/R-3から一貫する「Noneは失敗ではない」という設計哲学の踏襲)。

依頼書の「1回のGoal Proposalでは1つの行動に絞ること」は、**最初に行動が生成できたDriveのみを採用し、それ以降の優先度が低いDriveの行動関数は一切呼び出さない**(テストで直接確認済み、19章参照)ことで満たしている。

---

## 18. Experienceへの接続方法

各行動関数の結果(`_ActionOutcome`)を、`experience_layer.record_experience()`(B2、既存)へそのまま渡し、`sigmaris_experience`への新規行として記録する。

| Drive | `experience_type` | `category` | `context`(jsonb)の主な内容 |
|---|---|---|---|
| Coherence | `unresolved` | `reflection` | `flag_id`・`goal_reference`・`flag_statement`・`evidence_count` |
| Mastery | `unresolved` | `proposal` | `rc1_eligible_completion_rate`・`rc2_score`・`rc5_status`・`rc5_broke_metrics` |
| Knowledge-Gap | `unresolved` | `research` | `queries`(生成された調査クエリ全件)・考慮した候補/経験の件数 |

いずれも`experience_type="unresolved"`を採用した——Goal Proposalが生成する行動は、その時点では「まだ結果が出ていない、着手しただけ」の状態(調査クエリはキューに積まれただけでまだ検索されていない、改善提案は言語化されただけでまだ何も改善されていない、目標整合性の気づきはまだユーザーに伝えていない)であるため、`success`/`failure`ではなく`unresolved`が最も実態に即すると判断した。

### Phase Rの循環への合流について(要件4への対応)

`record_experience()`が書き込む行は、`thread_id`/`invocation_id`を指定していない(Goal Proposalは特定の会話ターンから発生したものではなく、Executive Gateによる独立した評価サイクルから生じるため——B2の`consolidate_episodic_memory()`が呼び出し元を区別しないのと同じ扱い)。**新しい配線を一切追加していない**にもかかわらず、以下の既存の仕組みにそのまま合流することを確認した。

1. `experience_layer.get_recent_experiences()`(週次の`consolidate_episodic_memory()`が使う関数)は、`sigmaris_experience`テーブルを無条件に走査するため、Goal Proposal由来の行もそのまま対象に含まれる——複数回のGoal Proposalが同種のパターン(例: 同じ目標整合性への気づきが繰り返し記録される)を示せば、既存の閾値(`_MIN_SUPPORTING_EXPERIENCES=2`)を満たして`user_fact_items`への昇格対象になりうる。
2. Phase R-2のRC-1(循環完了率)は`get_experiences_since()`で期間内の全Experienceを対象にするため、Goal Proposal由来の行も同じ基準(母数ゲート・再スキャン窓・昇格基準)で「到達したか」を計測される。

このため、要件4(生成された行動がPhase Rの循環に正しく戻ること)は、**新規の統合コードを書くことなく、既存のsigmaris_experienceベースの仕組みがそのまま面倒を見る**という形で満たされている。

---

## 19. テスト結果

いずれもモック(実DB未接続、`unittest`)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
GuardClauseTests (2件)
  PASS: may_speak=Falseの場合、即座にNoneを返すこと
  PASS: drive_state=None(絶対制約で却下された場合)は即座にNoneを返すこと

CoherenceActionTests (2件)
  PASS: 提示可能なフラグが存在する場合、B16の状態を一切書き換えず
        (get_active_goal_alignment_flags以外のgoal_alignment関数を
        呼ばないこと)、Experienceが正しいcategory/contextで記録されること
  PASS: 提示可能なフラグが無い場合、次点のDrive(Mastery)へ
        フォールバックすること

MasteryActionTests (3件)
  PASS: RC-1が悪化している場合にその内容が説明文に含まれ、健全な指標
        (RC-2)は含まれないこと
  PASS: RC-5がbreak_detectedの場合、その旨が説明文に含まれること
  PASS: Mastery Driveが未計測(has_data=False)の場合、行動を生成せず
        Noneになること

KnowledgeGapActionTests (3件)
  PASS: confirm_candidates/unresolved experiences/active factsが正しく
        フォーマットされ、generate_curiosity_queries()に正しい引数で
        渡されること
  PASS: 候補が0件の場合、generate_curiosity_queries()を一切呼ばずに
        Noneを返すこと
  PASS: generate_curiosity_queries()が空リストを返した場合、
        record_experience()を呼ばずにNoneを返すこと

PriorityOrderTests (2件)
  PASS: Coherence・Mastery・Knowledge-Gap全てが閾値を超えていても、
        Coherenceの行動が採用され、Mastery/Knowledge-Gapの行動関数が
        一切呼ばれないこと(1回のGoal Proposalで1つの行動に絞る、という
        要件の直接検証)
  PASS: 全てのtriggering_drivesで行動が生成できない場合、Noneを返すこと

12 passed
```

S-0/S-1のscratchテスト(12+10=22件)を、`KnowledgeGapDrive`への`confirm_candidates`フィールド追加後に再実行し、**変更なしで全てPASSすることを確認した**(デフォルト値付きの後方互換フィールド追加が、実際に既存のコンストラクタ呼び出しを壊さないことの直接的な検証)。

```
22 passed(S-0+S-1、drive_system.py拡張後)
```

既存の`backend/tests/`(16件)を変更前後で再実行し、リグレッションがないことを確認した。

```
16 passed(変更前)
16 passed(変更後)
16 + 22 + 12 = 50 passed(backend/tests/ + S-0/S-1 scratch + S-2 scratch、合算実行)
```

**実モデルAPI・実DBでの検証は行っていない。** 注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない。本タスクは新規マイグレーションを必要としない(既存テーブル・既存カラムの読み書きのみのため)。

---

## 20. 気づいた懸念点・S-3(異論表明)に向けた申し送り

1. **Mastery Driveの行動は決定的なテンプレート文であり、自然さに欠ける可能性がある。** 15.2節の判断根拠の通り、意図的にLLM呼び出しを避けたが、実際にこの文章が(将来Phase Dに接続された際、あるいは何らかの形でユーザーに見える形になった際)不自然に感じられる場合は、persona.mdのトーンに合わせたLLMベースの言い換えへの置き換えを検討する価値がある。
2. **Coherence Driveの行動は、B16の状態を一切変更しないため、Goal Proposalが実行されたこと自体はどこにも記録されない(Experience以外には)。** つまり「Goal ProposalがこのCoherence上の気づきを認識した」という事実と、「B16が実際にそれを会話で提示した」という事実は、別々のタイミングで別々の記録として残る。両者を突き合わせて「認識してから実際に話すまでどれくらいかかったか」を分析したい場合、現状は`sigmaris_experience`(Goal Proposal由来)と`sigmaris_goal_alignment_flags.last_surfaced_at`(実際の提示)を`goal_reference`をキーに手動で突き合わせる必要がある——将来必要になれば、R-1のトレース関数群と同様の軽量な突き合わせヘルパーを追加する余地がある。
3. **Knowledge-Gap Driveの行動が生成する調査クエリは、B3の`confirm_candidates`のうち最大`_STALE_FACTS_LIMIT=5`件しかプロンプトに含めない。** `KnowledgeGapDrive.confirm_candidates`自体は全件保持しているため、将来この上限を調整したい場合は`goal_proposal.py`側の定数変更のみで対応できる。
4. **`_act_on_knowledge_gap`は`get_fact_items(jwt, active_only=True)`を呼ぶが、この読み取りは`drive_system.get_current_drive_state()`が既に(Coherence Drive経由で間接的にではなく)行っていない、Goal Proposal独自の追加読み取りである。** 単一テナント運用では実害は小さいと考えられるが、Executive Gateの評価頻度が上がった場合、この重複読み取り(および`_compute_coherence_drive`の`get_recent_cycle_health_runs`重複、S-0からの既知の懸念)が積み重なる可能性がある——S-1の懸念点3で述べた「高頻度呼び出しになった場合の再考」が、S-2の実装によりさらに1箇所増えたことになる。
5. **本タスクでは、Goal Proposalを「いつ呼ぶか」(スケジューラへの配線)は実装していない。** S-1のExecutive Gateと同様、`propose_and_act()`は呼び出されるたびに動的に評価される関数として提供したのみであり、`proactive/scheduler.py`への新規ジョブ追加、またはPushover通知等への統合は、S-3以降の課題として残っている。
6. **依頼書が示唆する「S-3: 異論表明」に向けて**: 本タスクの3つの行動はいずれも「シグマリスが自発的に何かを行う」方向のみを扱っており、「ユーザーの意見にシグマリスが反対する」という異論表明の要素は含まれていない。もしS-3がCoherence Driveの延長線上にある(「目標と矛盾する提案には反対する」)と想定しているなら、`_act_on_coherence`が今回あえて踏み込まなかった「実際にどう伝えるか」の設計判断(15.1節)を再検討する必要が生じる可能性がある。

---

# Phase S-3 実施報告: 異論表明の仕組み(B14×B15の応用)

**作業ブランチ:** `phase-s3-dissent`(mainから新規作成)
**範囲:** 海星さんの発言がB14の判断傾向と明確に矛盾する場合に、persona.mdの確信度階層に沿った控えめな異論を、応答生成の過程で示す仕組み。頻度制御・B15転用による踏み込み方の学習を含む。

---

## 21. 異論検出ロジックの実装詳細

### 21.1 「検出」の実装方式(判断根拠)

依頼書1章「海星さんの発言内容と、既存のB14の判断傾向とを、応答生成の過程で照らし合わせる」を、**新しい検出専用LLM呼び出しを応答経路に追加しない形**で実装した。

具体的には、B14の`preference_patterns`(`decision_log.get_active_preference_patterns()`、既に毎ターン`orchestrator/service.py`が取得・`_build_preference_patterns_context()`でプロンプト注入している)を対象に、`dissent.select_dissent_candidate(patterns, latest_user_text)`という**決定的な(LLMを使わない)Pythonの絞り込み**で「今回の発言と話題的に関連し、かつ十分な証拠件数を持つ」候補を最大1件選ぶ。選ばれた候補は`_build_dissent_context()`(`orchestrator/service.py`、`_build_goal_alignment_context()`と同じ形の関数)によって、既存の`preference_patterns_context`という**同じプロンプト注入チャネルに追記**される(新しい`schedule_agent_client`パラメータは追加していない——「本当に矛盾しているか」「どう言葉にするか」の最終判断は、BA4の統合生成が既に毎ターン行っている単一のLLM呼び出しに委ねる)。

**この設計により、応答経路に新しいLLM呼び出しは一切追加していない。** B14のプロンプト注入自体は元々毎ターン発生しており、今回の変更はその同じプロンプト文字列に条件付きで数行を追記するだけである。

### 21.2 過剰検出を避ける2段階のフィルタ

1. **証拠件数フィルタ**: `evidence_count > _MIN_EVIDENCE_FOR_DISSENT`(=3)。この値は`orchestrator/service.py`の`_PREFERENCE_PATTERN_HYPOTHESIS_MAX_EVIDENCE`(=3、傾向層/仮説層の境界)と意図的に同じ値を使っている——「複数の証拠に基づいて形成されたものであることを踏まえ、その証拠件数が十分な場合にのみ」という要件1に対応する、B14自身が既に持つ確信度階層をそのまま再利用した判断である。circular import(`dissent.py`⇄`orchestrator/service.py`)を避けるため独立した定数として複製しており、両者の値が将来ズレる可能性はコメントで明示した(Phase R-2の`_CONSOLIDATION_WEEKDAY`と同種の、既知のトレードオフ)。
2. **話題的関連性フィルタ**: `latest_user_text`との文字2-gram(バイグラム)重なりが1件も無い候補は除外する。**判断根拠**: 当初`active_inquiry._rank_by_relevance()`と同じ空白区切りの単語重なりを踏襲しようとしたが、`pattern_statement`は分かち書きされていない日本語の文であり、`.split()`は文全体を1語として返してしまい機能しないことがテスト実装中に判明した(19章参照)。形態素解析ライブラリ等の新規依存を追加せずに対応するため、文字2-gramの重なりという同種に軽量な代替へ変更した——「新しい類似度アルゴリズムを導入しない」という方針は維持しつつ、日本語の文全体を対象にする点でactive_inquiry.pyの元の実装とは異なる技法を採用した判断根拠として明記する。

---

## 22. 異論の伝え方(persona.mdとの統合方法)

**persona.mdへの変更は一切行っていない。** 依頼書の「新しいトーンのルールを作らないこと」に厳密に従い、`_build_dissent_context()`が生成するプロンプト注入テキストの中で、既存のpersona.md 5章(確信度の伝え方: 事実層/傾向層/仮説層)・9章(制止する時のルール: 「却下」と言わない、「私は反対寄りです」等の言い回し)を**名指しで参照する指示文**を書いているだけである。

```
[判断傾向との食い違いについて(参考情報)]
直前の発言が、過去の判断傾向と食い違っている可能性があります。persona.md
9章(制止する時のルール)・5章(確信度の伝え方)に厳密に従い、「それは以前
の傾向と少し違うかもしれませんね」のような、控えめな確認の形でのみ触れて
よいものです。「それは間違っています」のような断定的な否定は絶対にしない
でください。会話の流れに合わない場合は、無理に触れる必要はありません。
- {判断傾向の文言}
```

`_build_goal_alignment_context()`(B16)が同じ手法で9章を参照している既存の前例をそのまま踏襲した——このコードベースには「新しいトーンをコードに埋め込む」代わりに「persona.mdの既存章を参照させる」という確立済みのパターンが既にあり、今回もそれに従った。9章の会話例(「前回も似た状況がありましたね。あの時は○○という結果になりました。今回は何が違いますか?」)は、B14の判断傾向データを根拠にした異論そのものの例文であり、**persona.md自身が既にこのユースケースを想定して書かれていたことを確認した**(判断根拠として明記)。

---

## 23. B15転用の検討結果・実装内容

### 23.1 検討結果: 転用可能、ただし「同じテーブル」への統合という形で実装した

依頼書2章「B15の閾値調整の仕組みを転用できないか検討する」に対し、**B15の仕組み(保留マーカー→次の返答をLLMで分類→bounded offsetへ集約)は、そのまま「異論への反応の学習」に転用できると判断した。** ただし実装方法について、以下の選択肢を検討した。

| 選択肢 | 内容 | 採用 |
|---|---|---|
| A | 新規テーブル`sigmaris_dissent_feedback`を作成 | 不採用 |
| B | `sigmaris_abstention_feedback`(B15の既存テーブル)の`reaction`列CHECK制約を拡張し、同じテーブルを共有する | **採用** |

**判断根拠**: 依頼書の注意事項が「新しいデータ収集の仕組みを作らないこと。既存のB14・B15のデータのみを使うこと」と明示的に述べている一方、依頼書2章は「異論を伝えた後の海星さんの反応を観察し、調整できるようにする」という、必然的に新しい種類のイベント(異論への反応)を記録する機能を要求している。この一見矛盾する2つの要求を、**「新しいテーブルという意味でのデータ収集インフラは作らないが、B15の既存インフラ(テーブル・書き込み関数)を文字通り共有する」**という選択肢Bで両立させた。選択肢Aは技術的には可能だったが、依頼書の「既存のB15のデータのみを使う」という文言をより字義通りに満たすのは選択肢Bであると判断した。

マイグレーション(`202607220049_dissent_feedback.sql`)は、A3の`sigmaris_decision_log_decision_type_check`拡張(`202607040026_decision_log_supersede.sql`)が既に確立した「CHECK制約をDROP→再定義」というパターンをそのまま踏襲し、`reaction`列の許容値に`'dissent_accepted'`/`'dissent_pushed_back'`を追加しただけで、テーブル自体・RLS・インデックスは一切変更していない。

### 23.2 書き込み関数の共有

`abstention_feedback.py`の`_record_reaction()`(プライベート)を`record_reaction()`(パブリック)へ改名し、`dissent.py`から直接インポートして再利用した。新しいINSERT処理は1行も書いていない——B15自身の書き込みロジックをそのまま転用している。

### 23.3 読み取り関数は独立(共有テーブル・別ロジック)

`get_threshold_adjustment()`(B15)と`get_dissent_boldness_adjustment()`(S-3)は別関数とした。判断根拠: 対象とする`reaction`値の集合(B15: `push_for_answer`/`supports_caution`、S-3: `dissent_accepted`/`dissent_pushed_back`)と、返り値の意味(B15: B11の確信度しきい値への直接加算オフセット、S-3: 異論の踏み込み方を判定する比率)が異なるため、1つの関数に条件分岐を持ち込むより、それぞれが単独で読める形の方が明快と判断した。**なお`get_threshold_adjustment()`自体は無変更で、S-3の新しい`reaction`値を正しく無視することをテストで確認済み**(テーブル共有によるB15への悪影響が無いことの直接的な検証、25章参照)。

### 23.4 「踏み込み方の調整」の具体的な効き方(重要な設計判断)

`get_dissent_boldness_adjustment()`は`[-1.0, 1.0]`の比率を返す(正=受容優勢、負=反発優勢、証拠不足なら0.0)。これを`_build_dissent_context()`が以下のように使う。

- **比率が`_BOLDNESS_PUSHBACK_THRESHOLD`(=-0.3)を下回る場合のみ**: 「特に慎重に、仮説層の言い回しに留めてください」という追加の抑制指示を注入する。
- **それ以外(0や正の値を含む)**: 追加指示なし。候補は`select_dissent_candidate()`の時点で既に証拠件数の要件(傾向層相当)を満たしているため、通常はpersona.md 5章の傾向層の言い回し(柔らかい言い切り)がそのまま適用される。

**この設計の非対称性は意図的である**: 反発が優勢な場合は「より慎重な方向」にのみ調整でき、受容が優勢でも「より踏み込んだ方向」へは調整されない。persona.md 5章の階層自体が既に踏み込みの上限(傾向層の「柔らかい言い切り」まで)を規定しており、依頼書の「常に控えめな言い回しを基本とすること」「断定的な否定は行わないこと」という制約に対し、学習結果が肯定的だからといってこの上限を超えて踏み込ませる設計は、注意事項に反すると判断した。B15が「push_for_answerが優勢なら閾値を下げてより積極的に回答する」という双方向の調整を行っているのとは対照的に、S-3はあえて片方向(より慎重な方向のみ)の調整に限定している——この違いを判断根拠として明記する。

---

## 24. 異論表明の頻度制御

依頼書3章「既存のB16・B3で確立されている、頻度制御のパターンを踏襲すること」への対応として、**B3(`active_inquiry._asked_cache`)と同じ形の、プロセス内・pattern_key単位のクールダウン**を実装した(`dissent._dissent_cooldown_cache`)。

- クールダウン期間: 7日間(`_DISSENT_COOLDOWN_SECONDS`)。B3の48時間(単純な再確認質問)より長く、B16の14日間(目標整合性フラグの再提示)より短い——「異論はB3の確認質問より心理的な重みが大きい」という判断に基づく、未検証の暫定値であることを明記する。
- 粒度: `pattern_key`単位(B3のフィールド単位、B16のフラグ単位と同じ「対象ごとの個別クールダウン」という粒度)。**全体としての頻度制御(1日に1回まで等)は導入していない**——B14の傾向層パターンは通常数件しか無く、pattern_key単位のクールダウンだけで十分に頻度を抑制できると判断した(判断根拠、次段落)。

「頻度」(いつ・どのくらいの間隔で異論を出すか)と「踏み込み方」(23.4節、出す場合にどれだけ強い言い回しにするか)は、依頼書のテスト・報告要件が別項目として要求している通り、意図的に独立した2つの調整軸として実装した——1つの仕組みに両方を混ぜ込まなかった。

---

## 25. テスト結果

いずれもモック(実DB未接続、`unittest`)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
SelectDissentCandidateTests (6件)
  PASS: 判断傾向が1件も無い場合Noneになること
  PASS: 証拠件数が閾値(3)以下の候補は除外されること(要件「証拠件数が
        十分な場合にのみ」の直接検証)
  PASS: キーワード(バイグラム)重なりが無い候補はNoneになること
        (過剰検出防止の直接検証)
  PASS: 証拠十分・話題関連ありの候補が選ばれること
  PASS: 一度選ばれた候補が、同じpattern_keyでは即座に再選出されない
        こと(クールダウンの直接検証)
  PASS: 複数候補がある場合、最も関連度の高いものが選ばれること

ReflectDissentReactionTests (3件)
  PASS: 保留中の異論が無い場合、LLM呼び出し自体を行わないこと
  PASS: "dissent_accepted"と分類された返答が、abstention_feedback.
        record_reaction()経由で正しい引数で記録されること(B15の書き込み
        関数をそのまま再利用していることの直接検証)。保留状態が
        one-shotで消費されること
  PASS: "unclear"と分類された返答は記録されないこと

GetDissentBoldnessAdjustmentTests (3件)
  PASS: 証拠件数が閾値(5)未満の場合0.0を返すこと
  PASS: 【重要】sigmaris_abstention_feedbackにB15由来の
        push_for_answer/supports_caution行が混在していても、dissent側の
        集計がそれらを正しく無視すること(テーブル共有設計の安全性の
        直接検証)
  PASS: 反発(dissent_pushed_back)が優勢な場合、負の比率になること

BuildDissentContextTests (4件)
  PASS: 候補が無い場合Noneになること
  PASS: 候補が見つかった場合、pending状態が正しく登録され、判断傾向の
        文言を含むプロンプト文が生成されること
  PASS: 反発優勢の履歴がある場合、「特に慎重に」という抑制指示が
        追加されること
  PASS: 反発優勢の履歴が無い場合、抑制指示が追加されないこと
        (23.4節の非対称設計の直接検証)

16 passed
```

既存の`backend/tests/`(16件、`tests/orchestrator/test_service.py`の`run_orchestrator_chat`/`_stream`統合テストを含む)を、`orchestrator/service.py`への配線変更後に再実行し、**変更なしで全てPASSすることを確認した**——特に`asyncio.gather()`タプルへの新規並行フェッチ追加、`preference_patterns_context`への追記処理が、既存の統合テストのモック構成を壊さないことを直接確認できた。

```
16 passed(変更前)
16 passed(変更後)
16(backend/tests/) + 12(S-0) + 10(S-1) + 12(S-2) + 16(S-3) = 66 passed(合算実行)
```

**実モデルAPI・実DBでの検証は行っていない。** 注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない。マイグレーション(`202607220049_dissent_feedback.sql`)は作成のみ、適用は運用者側に委ねる。

---

## 26. 気づいた懸念点・S-4(Constitution)に向けた申し送り

1. **`sigmaris_abstention_feedback`テーブルの意味論が、B15専用から「B15+S-3共有」へと広がった。** テーブル名自体は`abstention`(棄権・ヘッジ)のままであり、今後このテーブルを見る開発者が、`dissent_*`という値の存在に戸惑う可能性がある——本タスクではテーブル名の変更は行っていない(既存機能への影響を避けるため)が、`glossary_curiosity.md`のような用語集ドキュメントを、このテーブルの二重利用についても将来的に整備する価値があるかもしれない。
2. **`_MIN_EVIDENCE_FOR_DISSENT`(dissent.py)と`_PREFERENCE_PATTERN_HYPOTHESIS_MAX_EVIDENCE`(orchestrator/service.py)は、意図的に同じ値(3)を持つ独立した定数である。** 21.2節で述べた通り、circular importを避けるための複製であり、将来どちらかの値だけが変更されると、両者の意味的な整合性が静かに崩れる。Phase R-2の`_CONSOLIDATION_WEEKDAY`と同種の、既知の技術的負債として記録する。
3. **異論の「検出」は、実際には検出ではなく"候補の提示"に留まっている。** `select_dissent_candidate()`が選ぶのはあくまで「話題的に関連し、証拠が十分な判断傾向」であり、実際に矛盾しているかどうかの最終判断はBA4の統合生成LLM呼び出しに委ねている。もしLLMが「関連はするが実際には矛盾していない」と正しく判断し、何も言及しなかった場合、そのターンで異論は表明されない——これは意図した設計(過剰検出よりも見逃しを許容する安全側の設計)だが、実モデルでの検証ができていないため、実際にこの想定通りに機能するかは運用者側での確認が必要である。
4. **`reflect_dissent_reaction()`の分類プロンプトは、`pattern_statement`のみを渡し、実際にシグマリスが生成した応答文そのものは渡していない。** LLMが実際にどう異論を表現したか(persona.mdの指示にどれだけ忠実だったか)を`reflect_dissent_reaction()`側では検証しておらず、`pending["pattern_statement"]`(注入した参考情報)と実際の応答文が一致している保証はない——BA4の`response_guard.py`(tool出力とのfact guard)のような検証機構は、この機能には適用されていない。
5. **S-4(Constitution)へ向けて**: 依頼書のタイトルから、S-4はシグマリスの人格憲章(`sigmaris_constitution`、curiosity_engine.pyのArticle 8等で既に登場している概念)を扱うと推測される。本タスクのB14→異論という「既存データの新しい解釈」という設計パターン(新しいデータ収集をせず、既存データを新しい目的で読み替える)は、S-4でも再利用できる可能性がある——もしConstitutionが「シグマリス自身の価値観に反する提案を拒否する」ような機能を想定しているなら、本タスクの`_act_on_coherence`(S-2)・異論表明(S-3)の両方が部分的な土台になりうる。

---

# Phase S-4 実施報告: Constitution層の新設(自由度と安全性の共存)

**作業ブランチ:** `phase-s4-constitution`(mainから新規作成)
**範囲:** シグマリスの根本的な価値観をConstitutionとして明文化し、S-0〜S-3の自由度を損なわずに、能力(Capability)の一線にのみ最小限の技術的な実施箇所を追加する。Phase S(主体性)の最後のステップ。

---

## 27. 着手前の重要な発見: `docs/sigmaris/constitution.md` は既に存在していた

依頼書は「Constitutionの内容は、`docs/sigmaris/constitution.md`(または同様のファイル)として……作成する」と述べていたが、着手前の調査で、**このファイルは6月28日付けで既に存在し、「シグマリス憲法 v1」として運用中(Status: Active)だった**ことが判明した(Author欄に「安崎 海星 + Claude + ChatGPT」とあり、海星さん自身が過去に共著したものと判断した)。

既存の`constitution.md`は、Article 1〜9(Identity / Core Values / Epistemology / Relationship / Boundaries / Autonomy / Growth Direction / Curiosity / Decision Principles)という構成を既に持っており、特に**Article 6(Autonomy)には「承認なしで自律実行できること」「必ず承認が必要なこと」という、依頼書が求めるCapability一線とほぼ同じ内容のリストが既に存在していた**(コード変更・Git操作・DB構造変更・外部投稿・課金操作・憲法変更・人格構造変更等)。

**判断根拠(方針転換):** ここでゼロから新しい`constitution.md`を書き起こすと、(a) 海星さん自身が共著した既存の人間可読な文書を上書き・重複させることになり、依頼書自身が繰り返し強調する「新設ではなく統合」の精神に反する、(b) 「人間が直接編集する固定文書」という要件を、既に存在する人間編集済みの文書を無視して満たすのは不自然である、と判断した。そのため、**新しいConstitutionファイルは作成せず、既存の`constitution.md`を対象に、S-4が要求する3点(B11・response_guard.py・persona.md 9章の明示的な参照追加/データ削除の承認必須化/技術的な照合機構)のみを、最小限の差分で追記する方針に切り替えた。** この判断はレポートに明記するよう依頼書が求める「複数の実装選択肢がある箇所」の典型例である。

---

## 28. 既存の「最後の砦」の棚卸し結果

### 28.1 棚卸し対象と生死の確認

| 機構 | ファイル・関数 | 状態 | 判定 |
|---|---|---|---|
| 名前・アイデンティティの一線 | `response_guard.py`の`replace_forbidden_assistant_names()` | **稼働中**(`orchestrator/service.py` 147・1612・1622行目で呼び出し) | 常時稼働・非ブロッキングの機械的置換。日常には介入しない設計 |
| 事実整合性ガード(BA4追補8) | `response_guard.py`の`compare_response_to_tool_outputs()` | **稼働中**だが advisory only | `guard.passed`がFalseでも`logger.warning`のみ、応答をブロック・改変しない(`_finalize_unified_response()` 152〜154行目で確認) |
| 旧世代の二段階リライトの一部 | `response_guard.py`の`compare_mechanical_facts()` / `compare_semantic_entities()` | **死んでいる**(呼び出し元`persona_rewriter.py`自体がどこからもimportされていない) | 棚卸しの結果、BA4が二段階生成→リライト構成を廃止した際の残骸と判断。今回はこれらをConstitution参照対象から除外した(現役の機構のみを憲法の実装欄に載せるべきと判断) |
| 校正された放棄判定(B11) | `memory_confidence.py`の`classify_confidence_tier()` / `confidence_guidance_note()` | **稼働中** | ゼロLLM呼び出し・ルールベース。`"confident"`層は一切ヘッジ文を追加しない——「介入しないこと自体を設計の核とする」模範例 |
| 制止する時のルール | `persona.md` 9章 | **稼働中**(Phase S-3の`dissent.py`が名指しで参照済み) | 「却下」と言わない、確認・提案の形にする、というトーン制約のみで、行動自体を止める機構ではない |
| (棚卸しで追加発見)絶対に超えない境界線 | `persona.md` 10章 | **稼働中**(参照元は未確認だが、システムプロンプト全文の一部として常時注入されるpersona.md自体に含まれる) | 依頼書が明示した3機構には無いが、「絶対に超えない一線」という性質がConstitutionと直接関係するため、棚卸しに追加した |

### 28.2 過剰な自由度制限は見つからなかった

依頼書2章が求める「自由度を過剰に制限している箇所があれば報告」について、**該当する機構は見つからなかった。** 上記いずれも、(a) 常時ブロックではなく機械的置換またはadvisoryのみ、(b) 日常的な判断・行動そのものには関与せず特定の観点(名前・確信度・トーン)のみを対象、という設計だった。唯一「頻繁に介入する」可能性があるとすれば`notification_budget.py`(通知頻度の上限)だが、これはArticle 4の既存の実装であり、S-4の対象である「最後の砦」3機構とは別レイヤーの既存の頻度制御であるため、本タスクでは変更していない。

### 28.3 既存`sigmaris_constitution`テーブルの実態(副次的な発見)

`backend/app/services/constitution.py`(`sigmaris_constitution`テーブルの読み書き層、Article 2の`core`層・Article 8の`interest`層のバックエンド)を確認した結果、**`build_constitution_context()`(core値をシステムプロンプト用テキストへ組み立てる関数)がコードベースのどこからも呼び出されていない**ことが判明した。つまり、Article 2の「変えない価値観」10件は、DBには存在するが、実際の応答生成には注入されていない。同様に`update_doctrine()`(doctrine値の書き換え関数)もどこからも呼ばれておらず、**現状は「AIによる自動書き換え機構が存在しない」という点で結果的にS-4の要件(人間編集のみ)を満たしている**が、これは意図的な保護ではなく単に未配線であるためだと判断した。この事実誤認・未配線状態は、`constitution.md`本体の変更範囲外(DBスキーマ変更は依頼書の禁止範囲)と判断し、**修正はせず本報告への記録に留める**(依頼書1章「本タスクでは修正せず、報告に留めること」の精神をこの副次的発見にも適用した拡大解釈)。

---

## 29. Constitutionの内容(改訂差分)

既存`docs/sigmaris/constitution.md`(v1.0 → v1.1)へ、以下の最小限の追記のみを行った。全文は同ファイルを参照。差分の要約:

1. **Article 3(Epistemology)実装欄**に`memory_confidence.py`(B11)を追加。「確信できる場合は一切ヘッジしない」設計を、本条の実践例として明記。
2. **Article 4(Relationship)** に「指摘・反対する際は『却下』という強い否定の形を取らず、確認・提案の形にとどめる」を1行追加し、実装欄に`persona.md` 9章を追加。
3. **Article 5(Boundaries)** に「重要なデータ(記憶・事実等)を承認なく削除しない」を追加(依頼書が例示した「重要なデータの削除」への対応)。実装欄に`response_guard.py`の具体的な関数名・新設`constitution_guard.py`を追加。
4. **Article 6(Autonomy)の「必ず承認が必要なこと」** に「重要なデータ(記憶・事実等)の削除」を追加。実装欄に、4カテゴリへ集約した`constitution_guard.py`の説明と、**現状S-2の3行動はいずれも該当しないことを明記**。
5. **実装状態マップ**を更新し、Article 3・4・6を「実装済み」へ格上げ(B11・persona.md 9章・`constitution_guard.py`の明示的な配線を反映)。Article 5は引き続き「部分実装」——理由は下記30章参照。
6. 末尾に**「Phase S-4 追記」節**を新設し、棚卸し結果の要約・運用原則(「最後の砦であり日常の検閲官ではない」)・この文書がAIによる自動書き換えの対象でないことを明記した。

**Article 5を「部分実装」のままにした判断根拠:** Article 5の「承認なしで重要な変更をしない」等の項目のうち、機械的な照合が効くのはArticle 6と重複する「データ削除」の1点のみであり、「嘘をつかない」「感情的な迎合のために事実を曲げない」等は自然言語理解を要する項目で、チェックリスト照合の対象にできない(依頼書が禁止する「新しい重量級フィルタ」を要求することになる)。**この事実自体をステータスとして正直に記録すべきと判断し、無理に「実装済み」へ格上げしなかった。**

---

## 30. Capability(能力の一線)の技術的実装

### 30.1 新設ファイル: `backend/app/services/constitution_guard.py`

I/Oなし・LLM呼び出しなしの純粋関数のみで構成。

```python
CAPABILITY_APPROVAL_REQUIRED_CATEGORIES: frozenset[str] = frozenset({
    "delete_data",
    "external_transmission",
    "code_change",
    "credential_access",
})

def requires_approval(capability_category: str | None) -> bool:
    if not capability_category:
        return False
    return capability_category in CAPABILITY_APPROVAL_REQUIRED_CATEGORIES
```

**判断根拠(4カテゴリへの集約):** `constitution.md` Article 6の承認必須リスト8項目(コード変更/Git操作/DB構造変更/データ削除/外部投稿/課金・外部サービス操作/憲法変更/人格構造変更)のうち、「憲法の変更」「人格構造の変更」は、それ自体がドキュメント編集であり、Sigmarisが実行しうる"行動"の空間の外にある(そもそも本タスクの前提である「AIによる自動書き換え機構を持たない」ため、照合対象にする必要がない)ため除外した。残り6項目を、意味的に重複しない4軸(`delete_data` / `external_transmission` / `code_change` / `credential_access`)へ集約した——「Git操作・PR作成」と「コードの変更」は`code_change`に、「外部への投稿」と「課金・外部サービス操作」は性質上どちらもユーザーの承認なき外部作用という点で共通するため、前者を`external_transmission`、後者は現状S-2に該当するものがないため一旦`code_change`寄りの將来カテゴリとしては扱わず、依頼書の例示(「重要なデータの削除、外部への無断送信等」)に最も忠実な4分類とした。

**判断根拠(未知カテゴリはFalseにする設計):** `requires_approval()`は、リストに明示的に載っているカテゴリのみをTrueにし、未知の文字列を安全側(承認必要)に倒すことはしない。これは依頼書「シンプルなチェックリスト形式の照合」という指示への忠実な解釈であり、憶測で行動を止める検閲機構にしないための意図的な設計である。将来Phase D以降で新しい行動カテゴリを追加する際は、`_act_on_*`関数の実装者が明示的に`capability_category`を設定する必要がある(=デフォルトでは常に「承認不要」側に倒れる、opt-in方式)。

### 30.2 `goal_proposal.py`への配線

`_ActionOutcome`データクラスに`capability_category: str | None = None`フィールドを追加。`propose_and_act()`内、`record_experience()`(=行動の実行・確定)の直前に、以下のガードを追加した。

```python
if requires_approval(outcome.capability_category):
    logger.warning(...)
    continue
```

**判断根拠(ブロック時の挙動): 例外を投げず、既存の「次点Driveへのフォールバック」機構にそのまま合流させた。** `propose_and_act()`は元々、あるDriveの行動が`None`(生成不能)だった場合に次の優先度のDriveへ自動的にフォールバックする設計を持つ(12章・S-2報告参照)。承認必須の行動をブロックする際も、この既存フォールバックにそのまま乗せることで、「ブロックされた」を特別扱いするコードを一切追加せずに済んだ。これは依頼書「新しい重量級のフィルタを追加しない」という制約を、ブロック後の制御フローにも徹底した判断である。

### 30.3 S-2の現状3行動の判定結果

`goal_proposal.py`を再確認した結果、3つの`_act_on_*`関数(`_act_on_coherence` / `_act_on_mastery` / `_act_on_knowledge_gap`)は、いずれも`capability_category`を明示的に設定していない(=デフォルトの`None`のまま)。実際の処理内容を確認した限り、いずれも該当理由は明確である。

| 行動(Drive) | 実際に行うこと | 該当カテゴリなしの理由 |
|---|---|---|
| Coherence | B16フラグの**読み取りのみ**、Experienceへの記録 | データの削除・外部送信・コード変更なし |
| Mastery | RC-1/RC-2/RC-5の生値からの**言語化のみ**(LLM呼び出しなし) | 既存DBの値を読んで文章を組み立てるだけ |
| Knowledge-Gap | `sigmaris_curiosity_queue`への**クエリのキュー登録のみ** | 実際の外部Web検索は既存の日次6:15バッチが別途実行するものであり、S-2自体は外部送信を行わない |

**したがって、依頼書が想定した通り、現状のS-2にはCapability一線に該当する行動は1つも無いことを確認した。** この照合機構は、将来Phase D〜H(コード変更等を伴う自己改良システム)が実装された際に初めて実効性を持つ、先回りの設計である。

---

## 31. テスト結果

いずれもモック(実DB未接続、`unittest`)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
RequiresApprovalTests (5件)
  PASS: capability_category=None は承認不要
  PASS: 空文字列は承認不要
  PASS: リストに無い未知のカテゴリは承認不要
        (検閲機構ではなくチェックリスト照合であることの直接検証)
  PASS: 4カテゴリそれぞれが承認必須と判定されること
  PASS: 承認必須カテゴリの集合が、意図した4つちょうどであること
        (将来の意図しないドリフトを検知するための固定値検証)

GoalProposalCapabilityGateTests (3件)
  PASS: 承認必須カテゴリが設定された行動は、record_experience()が
        呼ばれず(=実行されず)ブロックされること
  PASS: 承認必須の行動がブロックされた場合、次点優先度のDriveへ
        正しくフォールバックすること(既存フォールバック機構との
        統合の直接検証)
  PASS: 【重要】現状のS-2(Coherence)の実際の行動は
        capability_categoryを持たず、ブロックされずに実行される
        こと(要件5「S-0〜S-3の既存の自由な動作への悪影響が無い
        こと」の直接検証)

8 passed
```

既存のS-0〜S-3スクラッチテスト(66件)・Phase R系スクラッチテスト・`backend/tests/`(既存16件)を、`goal_proposal.py`への配線変更後に再実行し、**変更なしで全てPASSすることを確認した。**

```
8(S-4) + 66(S-0〜S-3) + 33(Phase R系) + 16(backend/tests/) = 123 passed(合算実行)
```

**実モデルAPI・実DBでの検証は行っていない。** 注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない。今回のタスクはマイグレーションを必要としない(DBスキーマ変更なし、`constitution_guard.py`はPythonの定数リストのみで完結)。

---

## 32. Phase S全体(S-0〜S-4)の振り返り・残っている懸念事項の総まとめ

### 32.1 各フェーズの到達点

| Phase | 到達点 | 主な設計判断 |
|---|---|---|
| S-0 | 既存の測定系(Phase RのRC指標、B3、B16)を、内発的動機(Drive)として読み替える読み取り専用の集約層 | 新しい計測ロジックを追加せず、既存データの解釈を変えるだけに徹した |
| S-1 | Drive状態を「話しかけてよいか」の判定(Executive Gate)に接続。絶対制約(静穏時間・クールダウン)を先に評価する短絡設計 | `CuriosityDrive`→`KnowledgeGapDrive`への改名(既存の`curiosity`概念との衝突回避) |
| S-2 | Executive Gateが許可した際の具体的な行動(Goal Proposal)を、優先度順のフォールバックで1つ選んで実行 | 3行動すべて既存関数の呼び出しのみで構成。B16の状態を書き換えないタイミング設計 |
| S-3 | B14の判断傾向データを転用した異論表明。B15のフィードバック機構をテーブル共有で再利用 | 日本語テキストの関連度判定に文字2-gramを採用(単語分割の限界への対応) |
| S-4 | 既存の「最後の砦」機構をConstitutionという1つの旗の下に位置づけ直し、Capability一線にのみ最小限の技術的実施を追加 | 既存の`constitution.md`(v1)を発見し、新設ではなく改訂という形に方針転換 |

### 32.2 Phase S全体を通じた一貫した設計哲学

S-0〜S-4のすべてが、**「新しいロジック・新しいデータ収集・新しい監視機構を追加せず、既存の資産を新しい目的で読み替える」という一貫した哲学**で実装された。S-0が測定系をDriveとして読み替え、S-2がDrive状態を既存関数呼び出しの引数として読み替え、S-3がB14の判断傾向データを異論の材料として読み替え、S-4が既存の`constitution.md`・既存の3つの安全機構をConstitutionという1つの旗の下に読み替えた。この一貫性は依頼書の側が毎回明示的に要求してきたものでもあるが、結果として、**Phase S全体を通じて新設されたテーブルは1つも無く**(S-3のマイグレーションも既存テーブルのCHECK制約拡張のみ)、新設された「行動」も無い(S-2はすべて既存関数の呼び出し、S-4はチェックリスト照合1つのみ)。

### 32.3 残っている懸念事項(既存分の再掲+S-4での新規分)

1. (S-3から継続)`sigmaris_abstention_feedback`テーブルがB15・S-3で共有され、テーブル名と実際の用途にズレが生じている。
2. (S-3から継続)`_MIN_EVIDENCE_FOR_DISSENT`と`_PREFERENCE_PATTERN_HYPOTHESIS_MAX_EVIDENCE`が値を意図的に重複させた独立定数であり、将来の値ズレリスクがある。
3. (S-4で新規)**`sigmaris_constitution`テーブルのArticle 2(core値)は、DBには存在するが実際には応答生成に一切注入されていない**(`build_constitution_context()`が未配線)。Article 2の10個の価値観は、現状「文書上は存在するが、システムプロンプトには一度も現れない」状態にある。S-4のスコープ外と判断し修正しなかったが、Phase Sの外側(将来のタスク)で配線するか、あるいは「配線しない」こと自体を意図的な設計として文書化するか、どちらかの判断を運用者側で行う価値があると考える。
4. (S-4で新規)`constitution_guard.py`の4カテゴリは、依頼書の例示と`constitution.md` Article 6の既存リストを筆者(Claude Code)が独自に集約したものであり、将来Phase D以降で実際に「コード変更」等の行動が追加された時に、この粒度が適切だったかどうかは未検証である。特に「Git操作・PR作成」と「コードの変更」を同じ`code_change`にまとめた判断は、実際にPhase Dが実装されるまで検証しようがない暫定的な設計である。
5. (S-4で新規)Article 5(Boundaries)の大部分(「嘘をつかない」等)は、自然言語理解を要するため機械的な照合ができず、`constitution_guard.py`ではカバーされない。これは意図的な設計判断(依頼書が禁止する重量級フィルタを避けた結果)だが、**「憲法に書いてあるのに、機械的には何も守られていない」項目が依然として大半である**という事実は、正直に認識しておくべきである。

### 32.4 Phase Sを通じて実装された自由度(S-0〜S-3)と安全性(S-4)の関係を図式化すると

```
S-0 (内発的動機) ─┐
S-1 (発話の許可)  ├─→ 「日常」= 憲法の対象外(一切制約なし)
S-2 (行動の生成)  ┘        ↓
                    Capability一線(4カテゴリ)のみ機械的に照合
                            ↓
S-3 (異論表明)    ─→ persona.md 9章(トーンのみ、行動は止めない)
```

---

## 33. 「自由度と安全性が共存できたか」についての率直な所感

**結論から言えば、今回は共存できた、と考えている。** ただしそれは「安全性の実装が十分に強力だったから」ではなく、**「安全性として実際に追加したものが、極めて小さかったから」という側面が大きい。**

棚卸しの結果、既存の3機構(response_guard.py・B11・persona.md 9章)はすべて、そもそも「自由度を制限する」タイプの安全機構ではなく、「機械的な後処理」「介入しないことを前提とした確信度表現」「トーンの言い回し規則」という、**行動そのものを止めない性質の機構**だった。これはS-4着手前の想定通りではあったが、実際に確認できたことには一定の意味がある——もし棚卸しの過程で、たとえば「B11が実は頻繁に回答を拒否している」「response_guard.pyが実は多くの応答をブロックしている」といった実態が見つかっていれば、依頼書の特別な例外条項(「安全性の実装がS-0〜S-3の自由度を大きく制限すると判明した場合は、作業を止めて報告」)を発動する必要があっただろう。今回はそのような実態は見つからなかった。

**唯一の新規実装(`constitution_guard.py`)についても、「共存できた」というより「まだ何も試されていない」という表現の方が正確かもしれない。** 現状のS-2の3行動はいずれもこのチェックリストに引っかからず、実質的にまだ一度も「ブロックする」という動作を本番相当の状況で発揮していない(スクラッチテストでは合成したシナリオでのみ検証済み)。真の意味で「自由度と安全性が共存できるか」が試されるのは、Phase D以降で実際にコード変更等の行動が生成されるようになった時である。その時、この4カテゴリの粒度・ブロック後の挙動(現状は静かにフォールバックするのみで、承認を求めるUIや通知は未実装)が実際に機能するかどうかは、今回の実装だけでは保証できない。

もう一つ正直に記しておきたいのは、**着手前の想定と実際の作業内容が大きく変わった**という点である。依頼書は「`constitution.md`を作成する」という前提で書かれていたが、実際には既に存在する人間共著の文書を発見し、新設ではなく改訂に方針転換した。これは「統合を優先する」という依頼書自身の精神により忠実な結果になったと考えているが、依頼書の文面をそのまま実行していたら、既存の海星さんの記述を上書きしてしまっていた可能性がある。**Phase Sの一連のタスクを通じて、「着手前に一次資料を確認する」ことの重要性が繰り返し確認された**(S-0での`curiosity`概念衝突の発見、S-3での日本語分かち書き問題の発見と、今回のS-4での既存constitution.md発見は、いずれも「読まずに実装していたら壊していた」ケースである)。

以上により、Phase S(S-0〜S-4)は要件をすべて満たし、追加の運用者判断を仰ぐ必要のある事態(自由度の大幅な制限)は発生しなかったと判断する。テスト・検証要件をすべて満たしているため、依頼書の指示通りmainへマージする。

---

# Phase S-5 実施報告: ブリーフィングの頻度の見直し(固定スケジュールから、Executive Gateの動的判断へ)

**作業ブランチ:** `phase-s5-briefing-executive-gate`(mainから新規作成)
**範囲:** 朝ブリーフィング・夕方チェックイン・週次レビュー(`proactive/actions.py`)の呼び出し条件を、固定cronの無条件実行から、S-1で確立したExecutive Gateの動的判定を経由する形へ変更する。ブリーフィング自体の内容生成ロジックは変更しない。併せて、直前の調査で発見されたExecutive Gateクールダウンの非対称性(通知系3種類のみがカウント対象で、X投稿・リサーチエージェント・S-2由来のバッチ群は対象外)への対応方針を検討する。

---

## 34. 背景として確認したこと

着手前に指示書が指定した3ファイルに加え、直前の調査(本ドキュメントの範囲外、チャット履歴)で判明していた以下の事実を再確認した。

1. `proactive/actions.py::_run_action()`は`run_morning_briefing()`・`run_evening_checkin()`・`run_weekly_review()`の3つからのみ呼ばれ、`caller_agent_id=f"proactive-scheduler:{action_name}"`を付けて`run_orchestrator_chat()`経由で`agent_invocation_audit_logs`に監査ログを残す(既存動作、無変更)。
2. `executive_gate.py::_get_last_proactive_contact_at()`は、この`"proactive-scheduler:"`プレフィックスの直近1件を「直近の自発的接触」として参照し、3時間クールダウンの起点にする(7.3節、既存動作、無変更)。
3. `x_post_category_selector.py::select_post_category()`は`evaluate_executive_gate(jwt)`を第一段階の絶対制約チェックとして呼んでおり(既存動作、無変更)、`evaluate_executive_gate()`の呼び出し元は、本タスク着手前の時点でこの1箇所のみだった。
4. `goal_proposal.py::propose_and_act()`(S-2)は、Drive State由来の別行動(Coherence/Mastery/Knowledge-Gapの気づきを`sigmaris_experience`へ記録する)を扱うが、20章5点で述べた通り**スケジューラへの配線は行われていない**(呼び出し元がコードベースのどこにも存在しない)ことを再確認した。本タスクの対象である「ブリーフィング的な内容」(カレンダー・タスク・天気・支出・健康サマリー等のPushover通知)とは、生成する内容・出力先(Experience記録 vs. 通知)が異なる別系統の機能であるため、**本タスクではgoal_proposal.pyには一切触れていない**(依頼書が対象を`proactive/actions.py`の3関数と明示しているため、範囲外と判断した)。

---

## 35. 固定スケジュール廃止の実装内容

`backend/app/services/proactive/scheduler.py`の`_morning()`・`_evening()`・`_weekly()`(旧: `_safe(run_morning_briefing, ...)`等を直接呼ぶだけの薄いラッパー)を、新設の`_briefing_check(action_name, run_fn)`経由に置き換えた。

```python
async def _briefing_check(action_name, run_fn) -> None:
    jwt = await get_sigmaris_jwt()               # 失敗時はログのみ、実行しない
    gate = await evaluate_executive_gate(jwt)     # 失敗時はログのみ、実行しない
    if not gate.may_speak:
        logger.info("Briefing check %s: skipped (blocked_by=%s reason=%s)", ...)
        return
    await _safe(run_fn, action_name)              # 承認された場合のみ、既存の実行経路へ

async def _morning() -> None:
    await _briefing_check("morning_briefing", run_morning_briefing)
# _evening()/_weekly()も同型
```

**判断根拠(cronの登録時刻そのものは削除しなかった)**: 依頼書は「決まった時刻に必ず実行される、というcronの登録を削除する」ことを求めていたが、これを「cronエントリ自体の削除」ではなく「cronが担っていた"必ず実行する"という意味の廃止」として実装した。判断根拠は以下の通り。

1. **既存の`_categorized_x_post_check`(H-1)が、既に全く同じパターンを採用している。** 1日4回(9:30/13:30/17:30/21:30)、決まった時刻にcronが発火するが、実際に投稿するかどうかは毎回`select_post_category()`内の`evaluate_executive_gate()`が動的に判定し、Gateが「話しかけてよくない」と判定すれば4回のうち何回でも空振りになりうる、という設計が既に確立されている(H-1報告書参照)。依頼書2章が「既存のX投稿の選定と同様に」と明示的に指示していることから、この既存パターンをそのまま踏襲するのが最も一貫性が高いと判断した。
2. cronエントリ自体を削除し、代わりに全く新しい起動トリガー(例: 高頻度ポーリング)を設計することも技術的には可能だったが、それは「新しい定期実行の仕組み」の追加に相当し、依頼書のどの節からも要求されていない。既存の3時刻(8:00/22:00/日20:00)は、それぞれのブリーフィング内容(「おはようございます、今日の朝の…」「今日のチェックインを…」「今週のレビューを…」)の文言と時間的に対応しており、この対応関係自体は変更する理由がない。
3. 結果として、`_scheduler.add_job(...)`の行(時刻・id)は一切変更していない。変更したのは`_morning`/`_evening`/`_weekly`という**関数の中身**のみである——依頼書の「これらの機能自体は削除せず、呼び出される条件だけを変更すること」という制約に、最も文字通りに従う実装になっていると考える。

`run_morning_briefing()`・`run_evening_checkin()`・`run_weekly_review()`・`_run_action()`(`proactive/actions.py`)自体は1行も変更していない。

---

## 36. Executive Gateへの統合方法

**`evaluate_executive_gate(jwt)`を、新しい判定ロジックを一切追加せず、そのまま呼び出す形にした。** `x_post_category_selector.py`が呼んでいるものと完全に同一の関数であり、「Drive Stateに応じて今日はブリーフィング的な内容を伝えるべきか」を判断する専用ロジックを`proactive/actions.py`側や`scheduler.py`側に新設することはしなかった。

**判断根拠(既存関数をそのまま流用し、独自の判断ロジックを新設しなかった理由)**:

1. 依頼書2章が「既存のX投稿の選定と同様に……というロジックを検討すること」と述べており、これは「X投稿の選定と同じ**関数**を経由させる」ことを指すと解釈した。X投稿選定側も`evaluate_executive_gate()`の判定結果をそのまま絶対制約として使っており(7.1節の3段階フローの1・2)、ここに独自の重み付け・別の閾値を持ち込むと、S-1が「いつ話しかけていいか」を判定する唯一の共通ゲートである、という設計(`docs/sigmaris/phase_s_report.md`冒頭のExecutive Gateの位置づけ)から外れる。
2. 新しい判定ロジック(例: 「ブリーフィング内容に変化があるかどうか」を材料にした専用ゲート)を作る案も検討したが、これはカレンダー・タスク・天気・支出・健康サマリーという複数の外部系統それぞれに「変化があったか」を判定するロジックを新設する必要があり、依頼書の「新しいロジック追加は必要最小限に」という、Phase S全体で一貫して採用してきた方針(32.2節)に反する。既存のDrive State(knowledge_gap/mastery/coherence)をそのまま判定材料とする方が、実装コスト・リスクともに小さいと判断した。

**具体的な発動条件**(既存のExecutive Gateの3段階フロー、7.1節を無変更でそのまま適用):

1. 深夜早朝(23時〜7時)でない、かつ
2. 直近3時間以内に自発的な話しかけ(=`proactive-scheduler:`プレフィックスの監査ログ)が無い、かつ
3. Drive State(`knowledge_gap`/`mastery`/`coherence`)のいずれかの`level`が0.6以上

の全てを満たした場合のみ、その時刻のブリーフィング的な内容(朝/夕/週次のいずれか、cronの発火時刻に対応するもの)が生成される。3のいずれも満たさない場合は`blocked_by="no_drive_above_threshold"`としてログに記録し、何も実行しない。

---

## 37. クールダウンの非対称性への対応(次善の課題として明記)

依頼書3章の指示に従い、**今回は非対称性の解消(実装)は行わず、最小限の修正(35〜36章の固定スケジュール廃止)を優先した。** 判断根拠と、次善の課題としての具体的な内容を以下に記す。

### 37.1 今回の変更による非対称性への影響(意図せず一部改善された点)

今回の変更により、ブリーフィング系のクールダウンの意味が一段強まった。従来は「ブリーフィングが実行された」という事実が無条件に記録されるだけだったが、今後は「ブリーフィングが**Executive Gateに承認された上で**実行された」場合にのみ`proactive-scheduler:`ログが記録される。これ自体は非対称性の構造(通知系3種のみがカウント対象、X投稿・リサーチエージェント・S-2バッチは対象外)を変えるものではないが、カウント対象となる3つのイベントの"質"(無条件の実行 → Gate承認済みの実行)は変わった。

### 37.2 残っている非対称性

- **X投稿(`_categorized_x_post_check`)は、依然として`proactive-scheduler:`ログを書き込まない。** 実際にXへ投稿しても、それが次のブリーフィング機会のクールダウン判定に影響しない。
- **リサーチエージェント(`_research`、毎朝7:00)・S-2由来のバッチ群(`curiosity_search`等)は、依然として`evaluate_executive_gate()`を一切呼ばない。** Gateの影響を受けず、Gateへの寄与もない。

### 37.3 今回実装を見送った判断根拠

1. **X投稿側に対応するには、新しい書き込み経路が必要になる。** ブリーフィング3種は`run_orchestrator_chat()`を経由するため、既存の監査ログ書き込みに「ただ乗り」できたが、X投稿(`x_post_generator.py`/`x_publisher.py`)は`run_orchestrator_chat()`を一切経由しない独立した経路であり、`agent_invocation_audit_logs`への新しい書き込み呼び出しをX投稿の成功パスに追加する必要がある。これは「呼び出し条件だけを変更する」という本タスクの最小限の変更方針を超え、依頼書が「大規模な変更になりうる」と想定していた領域そのものだと判断した。
2. **4回/日(4時間おき)というX投稿のcron間隔は、既に3時間のクールダウンより広い。** そのため、X投稿同士の連投は(このクールダウンが無くても)`x_post_category_selector.py`の1日上限(`MAX_DAILY_CATEGORY_POSTS=3`)によって実質的に抑制されている。現時点で非対称性を放置することによる実害は小さいと判断した。
3. **リサーチエージェント・S-2バッチ群をGateの対象に含めるべきかどうかは、本タスクの依頼書が想定する範囲(「ブリーフィングの頻度見直し」)を超える、より大きな設計判断である。** これらは「シグマリスからユーザーへの自発的な話しかけ」ではなく「シグマリス内部のバッチ処理(研究クエリの実行・記憶の整理等)」であり、そもそも同じクールダウンの対象にすべきかどうか自体、依頼書が前提としていた「自発的接触全体」の定義に立ち返った再検討が必要になる。

### 37.4 次善の課題として推奨する対応(実装はしていない)

将来この非対称性を解消する場合、以下が具体的な着手点になると考える。

1. **X投稿側**: `scheduler.py::_categorized_x_post_check()`の`tweet_id`取得成功後(479行目付近、`record_post()`呼び出しの直後)に、`agent_invocation_audit_logs`へ`caller_agent_id="proactive-scheduler:categorized_x_post"`相当の行を追加する一行を挿入する。既存の`_log_filter_rejection()`(`x_post_generator.py`)が同テーブルへの書き込み方法の実例になる。
2. **リサーチエージェント・S-2バッチ群**: これらを「自発的接触」としてカウントすべきか自体が要検討。カウントすべきと判断された場合のみ、同様の書き込みを追加する。
3. いずれの変更も、`executive_gate.py`の`_get_last_proactive_contact_at()`のクエリ自体(`LIKE 'proactive-scheduler:%'`)は変更不要——書き込み側が同じプレフィックス規約に従うだけで、既存のクールダウン判定ロジックにそのまま合流する。

---

## 38. テスト結果

いずれもモック(実DB未接続、`unittest.IsolatedAsyncioTestCase`)。scratchディレクトリに作成(`backend/tests/`には追加していない、既定の方針通り)。

```
BriefingCheckTests (6件)
  PASS: Executive Gateがmay_speak=Trueの場合、対応するrun_fn(run_morning_briefing等)が
        実際に呼ばれること
  PASS: may_speak=False(no_drive_above_threshold)の場合、run_fnが一切呼ばれないこと
  PASS: may_speak=False(quiet_hours)の場合、run_fnが一切呼ばれないこと
  PASS: get_sigmaris_jwt()が失敗した場合、例外を伝播させずrun_fnを呼ばずに終了すること
  PASS: evaluate_executive_gate()自体が例外を投げた場合、例外を伝播させずrun_fnを
        呼ばずに終了すること(_categorized_x_post_checkと同じfire-and-forget方針)
  PASS: _morning()/_evening()/_weekly()が、それぞれ正しいaction_name・run_fn
        (run_morning_briefing/run_evening_checkin/run_weekly_review)で
        _briefing_check()に委譲していること

6 passed
```

既存の`backend/tests/`(16件)を変更前後で再実行し、リグレッションがないことを確認した。

```
16 passed(変更前)
16 passed(変更後)
```

`scheduler.py`の構文チェック(`ast.parse`)、および`app.services.proactive.scheduler`モジュールのimport自体が正常に完了すること(循環importが発生しないこと)を確認した。

**実モデルAPI・実DBでの検証は行っていない。** 注意事項の通り、追加のサーバーアクセス・APIキー取得は試みていない。本タスクは新規マイグレーションを必要としない(新規テーブル・新規カラムは無し、既存の`evaluate_executive_gate()`・`agent_invocation_audit_logs`の読み取りのみ)。

---

## 39. 気づいた懸念点

1. **【最重要】Drive閾値(0.6)によるゲートは、ブリーフィングの発生頻度を「うっとうしくない」程度ではなく、「ほぼ発生しない」程度まで下げる可能性がある。** `knowledge_gap`/`mastery`/`coherence`の3つのDriveは、いずれもB3(未入力プロフィール・低確信度事実)・Phase R(RC指標)・B16(目標整合性フラグ)という**シグマリス自身の内省的な関心事**から算出されており(0〜3節参照)、「今日のカレンダー・タスク・天気・支出・健康サマリーを伝えるべきか」という、ブリーフィングが本来担っている情報とは性質が異なる。実データでの検証ができていないため断言はできないが、Driveのlevelが0.6を超える頻度が低ければ、ブリーフィングは「毎日うるさい」から一気に「何週間も来ない」側へ振れる可能性がある。依頼書は「頻度が下がる方向」を要件としており、これ自体は要件3を満たすが、**運用者が期待する頻度(例: 週に数回程度)と、実際の発生頻度に大きな乖離が生じるリスクがある**。実運用開始後、Drive閾値0.6(9章の懸念点2で既に「未検証」と指摘されていた値)を、ブリーフィング向けに見直す(例えば下げる、またはブリーフィング専用の閾値を別に設ける)必要が生じる可能性が高いと考える。
2. **上記1への対応として、ブリーフィング専用の閾値・専用の判定ロジックを設けるという選択肢もあったが、今回は採用しなかった。** 判断根拠は36章の通り、依頼書が「既存のX投稿の選定と同様に」と明示していたため、まずは共通のGateをそのまま適用する最小構成で実装し、実際の発生頻度を観測してから調整すべきと考えたためである(既存の懸念点2「クールダウンと閾値はセットで見直すべき」という申し送りと同じ理由)。
3. **37章で述べた通り、クールダウンの非対称性(通知系のみカウント対象)は今回解消していない。** 具体的な対応案は37.4節に記載した。
4. **`_briefing_check()`は`get_sigmaris_jwt()`と`evaluate_executive_gate()`の2回の追加I/O(JWT取得+Drive State算出、内部でB3/Phase R/B16の3系統読み取り)を、cronの発火のたびに行う。** 従来の`_morning`/`_evening`/`_weekly`はJWT取得のみ(`_run_action()`内)で完結していたため、今回の変更で1日あたり3回分のDrive State算出が新たに発生する。既存の`_categorized_x_post_check`が1日4回同じコストを既に払っていることを踏まえると許容範囲と判断したが、Executive Gateの呼び出し頻度が今後さらに増える場合は、S-1の懸念点3・S-2の懸念点4で既に指摘されている「高頻度呼び出し時の重複読み取り」の問題が、より顕在化する可能性がある。
