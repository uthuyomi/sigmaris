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
