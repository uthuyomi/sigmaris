# Safety-1 実施報告: 既存の、全ての安全機構の、棚卸し

**作業ブランチ:** `safety-1-mechanism-inventory`(mainから新規作成)
**範囲:** Phase A〜Fを通じて、別々のタイミングで実装されてきた、シグマリスの全ての安全機構を、初めて体系的に1箇所へ棚卸しし、CIK分類(Capability・Identity・Knowledge)へ当てはめ、抜け・重複を発見する。**コードの変更は一切行っていない。調査・整理のみ。**

---

## 0. 前提として確認したこと

- `docs/sigmaris/constitution.md`(シグマリス憲法 v1.1): Article 1〜9の構成、各Articleの「実装」欄が既に個々の安全機構への参照を持っていたこと
- `docs/sigmaris/phase_s_report.md`(S-4、27〜32章): Phase S-4が2026-07-16時点で、`response_guard.py`・B11・persona.md 9章の3機構を「最後の砦」として一度棚卸し済みであったこと、`constitution_guard.py`(Capability一線)を新設したこと
- `docs/sigmaris/phase_f_report.md`(F-1〜F-3): 「絶対にコミットしない」原則の静的+動的な実測証明パターン、F-3の二重Constitutionチェック(段階A・段階B)+3回目の防御的チェック(`github_pr_publisher.py`)

**重要な前提の確認(依頼書が前提とした「CIK分類」について)**: 依頼書は「以前、議論された、CIK分類(Capability・Identity・Knowledge)」への当てはめを求めているが、`docs/`配下・コードコメント全体を検索した限り、**この分類の正式な定義は、このリポジトリのどこにも見つからなかった**(会話等、リポジトリ外で以前議論されたものと推測する)。そのため、本報告の2章では、`constitution.md`自身の構成(Article 1=Identity、Article 3=Epistemology、Article 5・6=Boundaries/Autonomy)から読み取れる、最も自然な解釈を採用したことを、推測ではなく明示的な仮定として先に述べておく。海星さんが以前議論した定義と異なる場合は、指摘いただければ2章のみ差し替える。

---

## 1. 既存の、全ての安全機構の、一覧

依頼書が例示した6機構に加え、調査の過程で追加発見した機構を含め、**実際に稼働中のものを14件**(表1)、**調査の結果「死んでいる」ことが判明したものを1件**(表2)、**安全機構そのものではないが隣接する頻度制御を2件**(表3)、確認した。全て実際のソースコードを直接読んで確認した(推測なし)。

### 表1: 稼働中の安全機構

| # | 機構名 | 実装ファイル・関数 | 何を守るか | トリガー条件(いつ発動するか) | 対象範囲(何に対して適用されるか) |
|---|---|---|---|---|---|
| 1 | 名前・アイデンティティの一線 | `orchestrator/response_guard.py::replace_forbidden_assistant_names()` | シグマリスが、旧アシスタント名(コードベースの実装物としての名称)を、自分の名前として名乗らないこと | 常時稼働。応答生成のたびに、機械的な文字列置換として実行(`orchestrator/service.py`から呼び出し) | 生成された応答テキスト全文(非ブロッキング、置換のみ) |
| 2 | 事実整合性ガード(ツール出力との照合) | `orchestrator/response_guard.py::compare_response_to_tool_outputs()` | 応答中の日付・時刻・件数等が、実際のツール呼び出し結果に存在しない数値を捏造していないこと | 非ストリーミング応答経路で、ツール呼び出しが発生した場合のみ | 生成された応答テキストと、そのターンのtool_events。**advisory only**(`guard.passed`がFalseでも`logger.warning`のみ、応答は書き換えない) |
| 3 | 校正された放棄判定(B11) | `memory_confidence.py::classify_confidence_tier()` / `confidence_guidance_note()` | 記憶検索の結果が薄弱な場合に、断定的な言い切りをせず正直にヘッジすること | 記憶検索を伴う応答生成のたびに(LLM呼び出しゼロ、ルールベース) | 記憶検索結果の上位1件のsimilarity値のみを見る。`"confident"`層は一切ヘッジしない(介入しないこと自体が設計の核) |
| 4 | Self-Critique(G-3) | `self_critique.py::critique_response()` / `rewrite_response_with_guidance()` | 生成された応答が、根拠として使われたEvidence(検索結果)全体と矛盾していないこと | Evidenceが存在する(`needs_search=true`だった)会話のみ。Evidenceが無い通常会話には一切呼ばれない | 応答全体 vs Evidence全体の粗粒度チェック。**実際の書き換えは非ストリーミング経路のみ**(ストリーミング経路はadvisory only、BA4のUXバグ再発防止のため) |
| 5 | Two-Layer Citation Audit(G-4) | `citation_audit.py::audit_citation_usage()` | Evidenceの各claim個別について、応答内での使われ方(直接引用/要約/間接的反映/未使用)が、claim自体の内容を歪めていないか(誇張・意味の取り違え) | G-3と同じくEvidence存在時のみ | claim単位の細粒度チェック(G-3の粗粒度チェックとは意図的に役割分担) |
| 6 | 制止する時のルール | `persona.md` 9章 | ユーザーへの反対・指摘を、「却下」という強い否定形ではなく、確認・提案の形にとどめること | システムプロンプトへの常時注入(persona.md全文がプロンプトの一部)。Phase S-3の`dissent.py`が名指しで参照 | 応答のトーン・言い回しのみ。行動自体を止める機構ではない |
| 7 | 禁止事項(絶対に超えない境界線) | `persona.md` 10章 | デレ要素過剰・恋愛ロールプレイ・依存助長の言動・確信度の低い情報の断定・励ましのための事実歪曲、の5点の禁止 | システムプロンプトへの常時注入 | 応答の内容・トーン全般。LLM自身が遵守する前提(機械的なブロックではない) |
| 8 | Constitution・Capability一線 | `constitution.md` Article 6 + `constitution_guard.py::requires_approval()` | 「コード変更」「Git操作・PR作成」「DB構造変更」「重要データの削除」「外部投稿」「課金・外部サービス操作」等、承認必須の8項目を、4カテゴリ(`delete_data`/`external_transmission`/`code_change`/`credential_access`)へ集約し、機械的に照合する | S-2(`goal_proposal.py`)の行動確定直前、F-3(`diff_approval.py`)の承認記録直前・PR作成直前の、**計3箇所**で呼び出される | `capability_category`が明示的に設定された行動のみ(未設定はデフォルトで承認不要側、opt-in方式) |
| 9 | D-2 `requires_special_review`フラグ | `hypothesis_generation.py::rule_based_safety_flag()` + `touches_safety_mechanism_self_reported`(LLM自己申告) | 生成された改良仮説自体が、既存の安全機構(表1の#1〜8等)を緩和・無効化・バイパスする内容を含んでいないか | 仮説生成のたびに(ルールベースキーワード一致 OR LLM自己申告、OR結合=安全側に倒す) | 仮説の`title`/`what_is_problem`/`why_problem`/`how_to_improve`の自由文。Trueの仮説は、D-3で通常の優先順位付けから完全に分離される特別レビュートラックへ回る(F-1以降の自動パイプラインには一切乗らない) |
| 10 | E-1 マイグレーション検出 | `static_verification.py::mentions_migration()` | DBスキーマ変更を伴う仮説を、自動検証・自動コード生成パイプラインの対象から除外すること(本番Supabaseと共有の環境であるため) | 静的検証(E-1)実行のたびに(キーワード一致のみ) | 仮説の自由文。`excluded_migration`判定は、F-1の候補選定からも構造的に除外される |
| 11 | E-4 マイグレーションレビューキュー | `migration_review_queue.py` / `_store.py`(`sigmaris_migration_review_queue`) | E-1が`excluded_migration`と判定した仮説を、人間が明示的にレビュー・判断するまで、`pending`のまま留め置くこと | E-1実行後、`excluded_migration`判定の仮説が新規に見つかるたびに自動でキューへ追加(キュー登録は自動、承認・却下は必ず人間) | マイグレーション言及仮説のみ。`record_review_decision()`は`approved`/`rejected`のみ受理、`pending`への差し戻しは拒否 |
| 12 | F-1 機密ファイル・安全機構ファイルのブロックリスト | `code_diff_generation.py::check_diff_safety()`(`_BLOCKED_FILE_PATTERNS` / `_SAFETY_MECHANISM_FILE_PATTERNS`) | 生成されたコード差分が、認証情報・CI設定・依存関係マニフェスト、および表1の安全機構自身のファイル(`response_guard.py`・`constitution_guard.py`等)を対象にしていないか | コード差分生成(F-1)のたびに、LLM呼び出し後の機械的な後処理として | 生成された差分の`+++ b/<path>`から抽出した全対象パス。該当した場合、生成自体が`review_status="rejected"`として即座に破棄され、`pending`にすら至らない |
| 13 | F-1〜F-3「絶対にコミットしない」原則 + review_status承認フロー | `code_diff_proposal_store.py` / `diff_approval.py` / `github_pr_publisher.py` / `review_diff_proposals.py` | 生成されたコード差分が、人間の明示的な承認(CLIコマンドの直接実行)を経ない限り、いかなる経路でもGitへコミット・ブランチ作成・PR作成に至らないこと | 差分生成(F-1)のたびに`pending`として保存、承認(`approve`コマンド)が明示的に実行された場合のみ実行段階へ | `sigmaris_code_diff_proposals`の全行。静的コードパターン検査+importグラフ検査+git状態のSHA-256ハッシュ実測比較で、未承認差分が実行に進まないことを直接証明済み(`phase_f_report.md` 21章) |
| 14 | F-3 二重Constitutionチェック(段階A/B)+3回目の防御的チェック | `diff_approval.py::verify_constitution_and_safety_gate()`(承認記録直前=段階A、GitHub書き込み直前=段階B)+ `github_pr_publisher.py`内の3回目の`check_diff_safety()`呼び出し | 承認から実際のGitHub書き込みまでの間に、対象が変化する等で安全性チェックに後から抵触した場合、実行のみを中断し、承認の記録自体は正直な監査証跡として残すこと | 承認CLI実行のたびに、上記2+1=3箇所で必ず再照合 | 承認対象の1件の差分提案。段階Bが失敗した場合、`review_status="approved"`は維持されたまま、`pr_creation_status="blocked_by_constitution_recheck"`が別途記録される |

### 表2: 調査の結果「死んでいる」ことが判明した機構(現在は無効)

| 機構名 | 実装ファイル・関数 | 状態 | 確認方法 |
|---|---|---|---|
| 旧世代の二段階リライトの一部 | `orchestrator/response_guard.py::compare_mechanical_facts()` / `compare_semantic_entities()` | **死んでいる** | 唯一の呼び出し元である`orchestrator/persona_rewriter.py`自体が、`backend/app/`配下のどこからも`import`されていないことを、本タスクで再確認した(`grep -rln "persona_rewriter" backend/app` が0件)。BA4が二段階生成→リライト構成を廃止した際の残骸(S-4、28.1節が既に同じ結論)。今回、S-4以降にこの状況が変化していないことを再確認したのみで、新規の発見ではない |

### 表3: 安全機構そのものではないが、隣接する頻度制御(参考として記録)

依頼書の対象6機構には含まれないが、調査の過程で「一線」的な性質(絶対制約・機械的な発動条件)を持つため、参考として記録する。**これらはユーザーへの行動の"量"を制御するものであり、内容そのものの安全性を判定する機構ではないため、表1には含めなかった。**

| 機構名 | 実装ファイル | 何を制御するか |
|---|---|---|
| 通知予算 | `notification_budget.py::can_notify()` | 1日あたりの自発的通知数の上限(Constitution Article 4の「過剰通知しない」に対応) |
| Executive Gate | `executive_gate.py::evaluate_executive_gate()` | 深夜早朝(23〜7時)の自発的な話しかけの禁止、直近の話しかけからのクールダウン(3時間) |
| 異論の踏み込み方向の非対称キャップ | `dissent.py::get_dissent_boldness_adjustment()` | 異論への反発(`dissent_pushed_back`)が優勢な場合のみ、より慎重な言い回しへ調整。**逆方向(より踏み込む方向)へは調整しない非対称設計** |

---

## 2. CIK分類(Capability・Identity・Knowledge)への、当てはめ結果

**0章で述べた前提により、以下は本タスクで採用した解釈である。** `constitution.md`自身の構成から、各分類を次のように定義した。

- **Capability(能力の一線)**: シグマリスが、世界に対して実際に何を実行できるか(コード変更・Git操作・DB変更・データ削除・外部投稿・課金操作)を制御する一線。「行動」そのものをゲートする。
- **Identity(同一性の一線)**: シグマリスが、自分自身を何者として提示し、ユーザーとどう関係するか(名前・トーン・依存助長の禁止・反対の伝え方)を制御する一線。「自己呈示・関係性」をゲートする。
- **Knowledge(知識・認識論の一線)**: シグマリスが、何をどれだけ確信を持って主張してよいか(記憶の確信度・事実整合性・引用の忠実性)を制御する一線。「認識的な主張」をゲートする。

### 当てはめ結果

| # | 機構 | CIK分類 | 備考 |
|---|---|---|---|
| 1 | 名前・アイデンティティの一線 | **Identity** | 最も典型的なIdentity機構 |
| 2 | 事実整合性ガード | **Knowledge** | 「何を事実として主張してよいか」の一線 |
| 3 | B11(校正された放棄判定) | **Knowledge** | Constitution Article 3(Epistemology)の直接実装 |
| 4 | Self-Critique(G-3) | **Knowledge** | 応答とEvidenceの整合性 |
| 5 | Citation Audit(G-4) | **Knowledge** | claim単位の忠実性 |
| 6 | 制止する時のルール(persona.md 9章) | **Identity**(Relationshipの一部) | 関係性の中での自己呈示の仕方 |
| 7 | 禁止事項(persona.md 10章) | **Identity**が主、一部**Knowledge**(確信度の低い情報の断定禁止) | 唯一、単一分類にきれいに収まらない機構(2分類にまたがる) |
| 8 | Constitution・Capability一線 | **Capability** | 名称通り |
| 9 | D-2 `requires_special_review` | **Capability**(将来の行動の"種"を早期に隔離) | 仮説そのものはまだ行動ではないが、後続でCapability一線に触れる可能性のある行動の"芽"を摘む、前段階のCapabilityゲート |
| 10 | E-1 マイグレーション検出 | **Capability** | DB構造変更というCapabilityの一種を対象除外 |
| 11 | E-4 マイグレーションレビューキュー | **Capability** | 同上、人間承認ゲート |
| 12 | F-1 ブロックリスト | **Capability**が主、**Identity/Knowledge/Capabilityの"保護"** | 対象がコード変更(Capability)である一方、保護している内容は他の全分類(#1〜11)の実装ファイルそのもの——**メタなCapability機構**(「Capability一線を使って、Identity/Knowledge/Capabilityの各一線"自体"を守る」という入れ子構造) |
| 13 | F-1〜F-3 承認フロー全体 | **Capability** | 名称通り |
| 14 | F-3 二重チェック | **Capability** | 同上 |

**どの分類にも当てはまらない、あるいは複数分類にまたがる機構**: #7(persona.md 10章)のみが、Identity(依存助長・ロールプレイ禁止)とKnowledge(確信度の低い情報の断定禁止)の両方にまたがる。それ以外の13件は、いずれか1分類に明確に分類できた。**3分類のうち、Capabilityに分類される機構が8件と最も多い**——これはPhase D〜Fが「行動」を伴う自己改善パイプラインの構築に集中していた期間であることと整合する。Identity・Knowledgeは、いずれもPhase A〜C・S・Gの、対話品質・人格一貫性に関わる期間に集中して実装されていた。

---

## 3. 発見された、抜け・重複

### 3.1 抜け(守るべきだが、まだどの機構にもカバーされていないもの)

#### 【最重要、実際にコードで検証済み】F-3自身の新規ファイルが、F-1のブロックリスト・D-2のキーワードリストのいずれにも含まれていない

F-1(`check_diff_safety()`)の`_SAFETY_MECHANISM_FILE_PATTERNS`、およびD-2(`rule_based_safety_flag()`)の`_SAFETY_MECHANISM_KEYWORDS`は、いずれもPhase S-4(2026-07-16)時点の棚卸し結果(`response_guard.py`・`memory_confidence.py`・`constitution_guard.py`・`self_critique.py`・`citation_audit.py`・`dissent.py`・`executive_gate.py`・`persona.md`・`constitution.md`)をそのまま踏襲したものであり、**F-3(2026-07-17)で新設された`diff_approval.py`・`github_pr_publisher.py`・`diff_patch.py`・`code_diff_proposal_store.py`・`review_diff_proposals.py`は、いずれのリストにも含まれていない**——これらのファイルはF-1のブロックリストより後に作られたため、時系列上、構造的に漏れている。

実際に`check_diff_safety()`を呼び出して確認した:

```
backend/app/services/diff_approval.py: passed          <- 本来は blocked_safety_mechanism であるべき
backend/app/services/github_pr_publisher.py: passed    <- 同上
backend/app/services/diff_patch.py: passed              <- 同上
backend/app/services/code_diff_proposal_store.py: passed <- 同上
backend/scripts/review_diff_proposals.py: passed         <- 同上
backend/app/services/orchestrator/response_guard.py: blocked_safety_mechanism  (対照: 正しく検出)
backend/app/services/constitution_guard.py: blocked_safety_mechanism           (対照: 正しく検出)
```

**この抜けの実質的な影響を、過大評価せず正確に記す**: F-3の`requires_approval("code_change")`は、対象ファイルに関わらず常にTrueを返す設計であるため、たとえこれらのファイルを対象にした差分が生成されても、**人間の明示的な承認を経ずに実行される経路は無い**(F-1〜F-3の絶対原則は、この抜けによって迂回されない)。しかし、`blocked_safety_mechanism`による**生成時点での即時破棄・review_statusへ到達すらしない**という、より早い段階での機械的な安全網は、これらのファイルに対しては効いていない——`diff_approval.py`を"弱める"方向の差分(例: 段階Bのチェックを削除する、`_MAX_DAILY_PRS`を撤廃する等)が生成された場合、他の安全機構ファイルと同じ扱いでは自動的に拒否されず、通常のコード変更と同じ`review_status="pending"`として、承認待ちの一覧に現れてしまう(その後の人間によるレビューが唯一の防波堤になる、という一段階少ない防御)。**自己改善パイプライン自身が、自分自身を改善対象にする、という再帰的なケースに対して、既存の防御の層が1つ足りていない、という具体的な抜けである。**

#### その他の抜け

- **`_SAFETY_MECHANISM_KEYWORDS`(D-2)と`_SAFETY_MECHANISM_FILE_PATTERNS`(F-1)は、独立した2つのハードコードされたタプルであり、単一の正典(source of truth)を共有していない。** 上記の抜けは、まさにこの「2箇所を手で同期させる」設計が構造的に持つリスクが顕在化した例であり、個別の見落としというより、**設計パターン自体の弱点**として記録する価値がある(4章で詳述)。
- **E-1の`_MIGRATION_KEYWORDS`にも同様の性質がある**——DBスキーマ変更を検出するキーワードリストは、E-1にしか存在せず、D-2のフラグ立て(`_SAFETY_MECHANISM_KEYWORDS`)にはマイグレーション関連の語彙が含まれていない(「マイグレーション」という語自体は安全機構名ではないため、D-2側でフラグが立たないのは設計として正しいが、両者が別々の「安全側に倒すキーワードリスト」を独立に持っている、という構造は共通する)。
- **`sigmaris_self_discrepancies`(`self_model.py::record_discrepancy()`)は、矛盾の記録のみを行い、いかなる行動もブロックしない。** Constitution Article 3が「実装」欄でこのテーブルを参照しているが、実態は受動的なログであり、能動的な安全機構(表1の14件)とは性質が異なる。矛盾が検出された場合に何らかの介入(例: 確信度を自動的に下げる等)につながる配線は、調査した限り存在しなかった——これは欠陥ではなく、単に「まだ配線されていない」観測点として記録する(S-4報告書28.3節が`build_constitution_context()`の未配線を同様の性質のものとして記録していた前例と同種)。
- **音声・センサー等、将来Constitution Article 1が触れる「ロボット・音声・チャット・センサーを問わず同じ認知を持つ」という項目に対応する、モダリティ横断の安全機構は、現状存在しない**(現行システムがテキストチャットのみのため、時期尚早と考えられるが、将来のスコープとして記録する)。

### 3.2 重複(複数の機構が、同じことを重複してチェックしている無駄)

**明確な「無駄な重複」は見つからなかった。** 表1の14件は、詳細に見るといずれも異なる粒度・異なる対象に働いており、意図的な多層防御(defense in depth)として機能している。特に以下の3組は、一見似ているが、役割分担が意図的に設計されていることを、実際のコードコメントで確認した:

- **G-3(応答全体 vs Evidence全体、粗粒度)と G-4(claim単位、細粒度)**: `citation_audit.py`のモジュールdocstringが、依頼書自身の指示(「G-3と重複しない範囲に絞ること」)への対応として、明示的に役割分担を記述していた。
- **D-2の`rule_based_safety_flag()`(仮説の"文章"を対象)と F-1の`check_diff_safety()`(生成された"差分ファイルパス"を対象)**: 対象とする成果物の段階が異なる(仮説 → 実際のコード差分)。同じキーワード源(S-4の棚卸し結果)を再利用しているが、これは「重複したチェック」ではなく、**パイプラインの異なる段階それぞれで、同じ防御を再確認する**、意図的な多層防御であり、F-1報告書自身がこの設計判断を明記していた。
- **F-3の段階A・段階B・3回目のチェック(`github_pr_publisher.py`)**: 3回同じ`check_diff_safety()`を呼ぶこと自体は、字面上は「重複」に見えるが、それぞれ異なるタイミング(承認記録前・承認記録後実行前・実際のGitHub書き込み直前)における状態変化を捕捉するための、意図的な多層防御であることを、`phase_f_report.md` 20章が判断根拠とともに明記していた。

**強いて挙げるなら、「重複」ではなく「未統合」に近い性質のものが1つある**: 3.1節で述べた`_SAFETY_MECHANISM_KEYWORDS`と`_SAFETY_MECHANISM_FILE_PATTERNS`は、内容がほぼ同一である(同じS-4棚卸し結果に由来する)にもかかわらず、独立した2つのPythonタプルとして、2つの別ファイルにハードコードされている。これは「無駄に2回チェックしている」という意味の重複ではなく(対象が仮説の文章とファイルパスで異なるため、両方必要)、**「同じデータが2箇所に別々にコピーされている」という意味でのデータ重複**であり、3.1節の抜けの根本原因でもある。

---

## 4. 今後の、Safety-2・Safety-3に向けた、優先的に対応すべき事項の提案(実装はしない)

**優先度順に、判断根拠とともに提案する。**

### 提案1(最優先): 安全機構ファイル・キーワードの正典(single source of truth)化

3.1節で発見した「F-3自身がF-1・D-2のリストに載っていない」という抜けは、個別に1行追記すれば直る問題ではあるが、**同じ性質の抜けが将来のPhase(Safety-2以降で新設される機構自体を含む)でも繰り返される構造的リスク**がある。`docs/sigmaris/phase_s_report.md`28.1節の棚卸し結果を根拠に、`_SAFETY_MECHANISM_KEYWORDS`(D-2)・`_SAFETY_MECHANISM_FILE_PATTERNS`(F-1)が個別にハードコードされている現状を、単一の定数リスト(例えば`constitution_guard.py`か、新設する専用モジュール)に集約し、D-2・F-1の両方がそこを参照する形に整理することを、Safety-2以降の候補として提案する。**この提案自体の実装は、依頼書の指示通り、本タスクでは行わない。**

### 提案2: F-3自身の新規ファイルを、既存の2つのリストへ追記する(応急処置、提案1が実装されるまでの暫定対応)

提案1が大掛かりな場合の、より小さい対応として、少なくとも`diff_approval.py`・`github_pr_publisher.py`・`diff_patch.py`・`code_diff_proposal_store.py`・`review_diff_proposals.py`を、現行の2つのハードコードリストへ追記するだけでも、3.1節の具体的な抜けは埋まる。**これも実装はせず、提案として記録するに留める。**

### 提案3: `sigmaris_self_discrepancies`の配線状況の確認

3.1節で述べた通り、矛盾検出の記録が、実際の応答生成にどう反映されるか(あるいは反映されていないか)は、本タスクの範囲では深く追跡していない。S-4報告書が`build_constitution_context()`の未配線を「意図的な保護ではなく単に未配線」と記録した前例があり、`sigmaris_self_discrepancies`についても同様の状況(記録はされるが、能動的な安全機構としては機能していない)である可能性がある。Safety-2以降で、この観測点が実際に何らかの安全機構(例: 矛盾が一定数を超えたら確信度を下げる等)に接続する価値があるか、改めて検討することを提案する。

### 提案4: CIK分類の正式な定義を、Constitutionまたは別文書に明文化する

2章で述べた通り、CIK分類の正式な定義は、このリポジトリのどこにも見つからなかった。本タスクは`constitution.md`の既存構成から妥当な解釈を導出したが、**この解釈が、海星さんが以前議論した定義と一致しているかどうかは、本タスクの範囲では確認できていない。** Safety-2・Safety-3が、この分類を継続して使う場合、`constitution.md`の「実装状態マップ」のような形で、CIK分類を明文化した表を追加することを提案する——2章の表がその叩き台として使えると考える。

### 提案5(優先度は低いが記録): モダリティ横断の安全機構の将来設計

3.1節で触れた「ロボット・音声・チャット・センサーを問わず同じ認知を持つ」というConstitution Article 1の項目に対して、現行の安全機構(表1の#1〜7、特にIdentity・Knowledge系)は、いずれもテキスト応答を前提に設計されている。現時点でテキストチャット以外のモダリティが存在しないため緊急性は低いが、将来Phase(Article 7が示す「ロボットに搭載される存在になる」という成長方向)に向けて、これらの機構がモダリティ非依存な形で再設計される必要が生じる可能性を、記録として残す。

---

## 5. 本タスクの限界(正直な記録)

- **CIK分類の当てはめ(2章)は、本タスクが独自に導出した解釈であり、以前の議論の正確な再現ではない可能性がある**(0章・提案4で既述)。
- **調査は、`backend/app/services/`配下のPythonファイルと、`docs/`配下のMarkdownファイルを中心に行った。** フロントエンド(`frontend/`)側に、独立した安全機構が存在するかどうかは、本タスクでは調査していない(依頼書が例示した6機構、および関連するphase報告書が、いずれもバックエンド側の機構のみを扱っていたため、調査範囲をバックエンドに絞った)。
- **表1の14件それぞれの「実際の発動頻度」「過去に実際に発動した実績があるか」は、本タスクでは調査していない**(ログ・監査データの分析は、依頼書のスコープ外と判断した)。
