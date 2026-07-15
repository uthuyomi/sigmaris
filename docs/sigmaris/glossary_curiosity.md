# 用語集: 「curiosity」を名乗る3つの概念

**作成日**: 2026-07-15
**目的**: このコードベースには「curiosity(好奇心)」という言葉を含む、互いに無関係な3つの概念が存在する。今後、この用語を使うタスク指示書・コード内コメント・設計議論では、**必ずこのドキュメントを参照し、どの概念を指しているかを明示すること**を推奨する。

---

## 一覧

| # | 正式名称(推奨表記) | 実体 | 状態 |
|---|---|---|---|
| 1 | **curiosity mood**(好奇心ムード値) | `sigmaris_internal_state.curiosity` | 既存・稼働中 |
| 2 | **curiosity research queue**(好奇心リサーチキュー) | `curiosity_engine.py` / `sigmaris_curiosity_queue` | 既存・稼働中 |
| 3 | **Knowledge-Gap Drive**(知識ギャップ動機) | `drive_system.py::KnowledgeGapDrive` | Phase S-0で新設・S-1で改称済み |

以下、それぞれを詳述する。

---

## 1. curiosity mood(`sigmaris_internal_state.curiosity`)

### 何を表すか

会話ターンごとに`min(1.0, 現在値 + 0.01)`で**単調増加する**、シグマリスの"雰囲気"を表すfloat値(0.0〜1.0、デフォルト0.5)。`confidence`・`concern`・`urgency`・`stability`・`trust_in_context`と並ぶ、`sigmaris_internal_state`テーブルの1列。

### 書き込み元(唯一)

`orchestrator/service.py::_cognitive_layer_bg()`(会話ターンごとのfire-and-forget処理)が、他5系統の認知処理(decision検出・episode検出・確認質問の反映・話題遷移検出・棄権フィードバック反映)の完了後に、無条件で`+0.01`する。**会話の内容・B3の未解決事項の量・その他いかなる実データとも連動しない。**

### 読み取り・参照箇所(調査時点で確認できた全て)

| 箇所 | 用途 |
|---|---|
| `internal_state.py::snapshot()` | `confidence`等と一緒にまとめて返す(自己参照用の圧縮ビュー) |
| `decision_log.py::detect_and_record_decision()`(880行) | `sigmaris_decision_log.internal_state_snapshot`(jsonb)へ、決定検出のたびに**そのまま埋め込むだけ**——決定内容には一切影響しない、監査目的の記録 |
| `routes/agent.py::GET /agent/state`(1099行) | 外部エージェント向けデバッグ用に、state全体をそのまま返す |

### 【重要な発見】現時点では、いかなる判断・挙動にも使われていない

`internal_state.py::get_intervention_level_from_state()`(介入レベルの算出)は`urgency`・`concern`のみを参照しており、**`curiosity`列は一切使っていない。** 上記の参照箇所3件も、いずれも「そのまま保存する」「そのまま返す」だけで、この値を条件分岐やスコアリングに使っている箇所は、調査した範囲では見つからなかった。

**結論: `sigmaris_internal_state.curiosity`は現状、書き込まれ続けるが挙動には一切影響しない、事実上の"生きたテレメトリ"に留まっている。** これは本タスクが指摘する新規の懸念点であり、5章で扱う。

---

## 2. curiosity research queue(`curiosity_engine.py` / `sigmaris_curiosity_queue`)

### 何を表すか

シグマリスが**外部の情報源(HackerNews・arXiv等)を能動的に調べるべき、具体的な検索クエリ**を溜めるキュー。1行が1つの検索クエリ(`query`・`reason`・`source`・`priority`・`status`)を表す。人格憲章(Article 8、`sigmaris_constitution`)が定める「関心軸」の具体化、というPhase以前からの設計意図を持つ。

### 参照元3箇所の実際の使われ方

| 参照元 | 役割 |
|---|---|
| `research_agent.py`(674行、日次トレンド調査ジョブ内) | 調査したが関連度LOWと判定された、かつタイトルが興味深い項目を、最大3件まで自動的にキューへ追加(`source="trend"`) |
| `proactive/scheduler.py::_curiosity_search`(日次6:15) | `curiosity_engine.execute_curiosity_search()`を呼び、pendingのクエリを最大5件、`research_agent.run_research_for_query()`で実際に検索実行し、ステータスを`done`/`skipped`に更新する |
| `proactive/scheduler.py::_self_interest_queries`(日曜5:30、Article 8) | `curiosity_engine.generate_self_interest_queries()`を呼び、人格憲章の関心軸からランダムに1〜2件選び、ユーザー文脈と組み合わせてLLMに具体的な検索クエリを生成させ、キューへ追加(`source="self_model_gap"`) |
| `routes/agent.py::GET /curiosity/queue`(1134行) | 外部エージェント向けに、pending中のキュー内容を返す読み取り専用エンドポイント |

### 【重要な発見】`generate_curiosity_queries()`は呼び出し元が存在しないデッドコード

`curiosity_engine.py`には、上記4箇所のいずれからも呼ばれていない`generate_curiosity_queries()`(232行)という関数が存在する。このプロンプト(`_GENERATE_PROMPT`)は「ユーザー事実サマリー」「**直近の未解決経験**」「**古くなった可能性がある事実**」という3つの入力からクエリを生成する設計になっており、これはまさに**B3(`active_inquiry.py`/`memory_validator.py`)が扱う「確信度の低い/古い事実」「未解決の経験」と同種のデータ**を入力として想定している。しかし実際にこの関数へB3由来のデータを渡す配線は一度も実装されないまま、現在に至るまで死んでいる。

この発見は3章の統合可能性の検討に直接関わる重要な手がかりである。

---

## 3. Knowledge-Gap Drive(`drive_system.py::KnowledgeGapDrive`、旧称 Curiosity Drive)

### 何を表すか

B3(`active_inquiry.py`/`memory_validator.py`)が既に持つ、**シグマリスがユーザーについてまだ知らない、または確認が必要な情報の量**を、0.0〜1.0の`level`に集約した値。`get_null_fields()`(未入力プロフィール項目)と`get_confirmation_candidates()`(低確信度・矛盾フラグ・長期未更新の既存事実)の件数を、8件で飽和する形で正規化する。

新規データは一切生成しない、既存データの読み取り専用の集約層(Phase S-0で新設)。Phase S-1で、本ドキュメントが扱う名前衝突を理由に`CuriosityDrive`から改称された。

### 想定されている将来の使われ方

`docs/sigmaris/phase_s_report.md`(S-0・S-1セクション)によれば、S-1(Executive Gate、実装済み)が`DriveState`の3つのDrive(Knowledge-Gap・Mastery・Coherence)のいずれかが閾値(0.6)を超えていれば「自発的に話しかけてよい」と判定する材料として使っている。S-2(Goal Proposal、未着手)が、実際に「何を話すか」を生成する際の判断材料として使う想定。**いずれも「ユーザーへの自発的な話しかけ」という文脈に閉じており、外部情報源の検索とは無関係。**

---

## 3つの関係性(一覧比較)

| 観点 | curiosity mood | curiosity research queue | Knowledge-Gap Drive |
|---|---|---|---|
| 対象 | シグマリス自身の"雰囲気" | 外部世界(Web) | ユーザーとの関係(B3) |
| データの性質 | 抽象的なfloat1つ | 具体的な検索クエリの集合 | 抽象的なfloat1つ+内訳 |
| 実データとの連動 | **無し**(機械的に増加するのみ) | 有り(research_agent/self-interest由来) | 有り(B3の実候補件数) |
| 現在の挙動への影響 | **無し**(書き込まれるだけ) | 有り(実際に検索が実行される) | 有り(S-1のExecutive Gateが参照) |
| 導入時期 | Phase A以前から存在(詳細な導入時期は本調査未特定) | Phase以前から存在(Article 8関連) | Phase S-0(2026-07-14) |

---

## 用語の使用ルール(今後のタスク指示書・コメントへの提案)

1. 単に「curiosity」とだけ書かず、**上記の推奨表記(curiosity mood / curiosity research queue / Knowledge-Gap Drive)のいずれかを明示する**こと。
2. コード内で新たにこれら3つのいずれかに触れる変更を行う場合、変更対象のファイル冒頭コメント・関数docstringに、他の2つとの違いを一言添えることを推奨する(4章で実施した注釈を前例として参照してよい)。
3. 3つを同時に扱うタスクでは、必ず本ドキュメントへのリンクを指示書冒頭の「着手前に確認すること」に含める。
