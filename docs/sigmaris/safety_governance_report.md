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

---

# Safety-2 実施報告: 安全機構リストの統合、及び、CIK分類の正式な定義

**作業ブランチ:** `safety-2-list-consolidation-cik`(mainから新規作成)
**範囲:** Safety-1が発見した、D-2(`hypothesis_generation.py`)とF-1(`code_diff_generation.py`)の、独立してハードコードされた2つの"安全上重要なファイル"リストを、単一の正典へ統合する。あわせて、CIK分類(Capability・Identity・Knowledge)を正式に定義し、Safety-1が棚卸しした14の安全機構を再分類する。**D-2・F-1、それぞれの判定ロジック自体(キーワード一致 vs ファイルパスパターン一致)は、一切変更していない。**

---

## 6. 統合された、リストの、実装内容

### 6.1 新設モジュール: `backend/app/services/safety_critical_files.py`

I/Oなし・LLM呼び出しなしの純粋なデータ定義モジュール。`SafetyCriticalFile`(`name`/`file_pattern`/`keywords`/`origin_phase`の4フィールドを持つ、frozenなdataclass)のタプルとして、安全上重要なファイルを一元管理する。

```python
@dataclass(frozen=True)
class SafetyCriticalFile:
    name: str
    file_pattern: str        # F-1::check_diff_safety()が re.search() で照合
    keywords: tuple[str, ...]  # D-2::rule_based_safety_flag()が部分一致で照合
    origin_phase: str        # 由来の追跡用(判定ロジックには使わない)

SAFETY_CRITICAL_FILES: tuple[SafetyCriticalFile, ...] = (...)

def get_safety_mechanism_keywords() -> tuple[str, ...]:
    return tuple(kw for entry in SAFETY_CRITICAL_FILES for kw in entry.keywords)

def get_safety_mechanism_file_patterns() -> tuple[str, ...]:
    return tuple(entry.file_pattern for entry in SAFETY_CRITICAL_FILES)
```

`hypothesis_generation.py`・`code_diff_generation.py`側の変更は、ハードコードされていたタプルリテラルを、この2関数の呼び出しへ置き換えただけである。

```python
# 変更前(hypothesis_generation.py)
_SAFETY_MECHANISM_KEYWORDS = (
    "response_guard", "response_guard.py", ...  # 25個のハードコードされた文字列
)

# 変更後
from app.services.safety_critical_files import get_safety_mechanism_keywords
_SAFETY_MECHANISM_KEYWORDS = get_safety_mechanism_keywords()
```

```python
# 変更前(code_diff_generation.py)
_SAFETY_MECHANISM_FILE_PATTERNS: tuple[str, ...] = (
    r"response_guard\.py$", ...  # 9個のハードコードされた正規表現
)

# 変更後
from app.services.safety_critical_files import get_safety_mechanism_file_patterns
_SAFETY_MECHANISM_FILE_PATTERNS: tuple[str, ...] = get_safety_mechanism_file_patterns()
```

**判定ロジック自体(`rule_based_safety_flag()`の`keyword.lower() in haystack.lower()`によるループ、`check_diff_safety()`の`re.search(pattern, normalized)`によるループ)は、1行も変更していない。** 依頼書の制約「既存の判定ロジック自体は変更しないこと」への直接対応。

### 6.2 収録対象を、依頼書が明示した3ファイルから、9ファイルへ拡張した判断根拠(独断で決めた箇所)

依頼書は「`diff_approval.py`・`github_pr_publisher.py`・`diff_patch.py`**等**」と例示した。この「等」を、以下の判断基準で拡大解釈し、自己改善パイプライン(D-2〜F-3)全体の中で**実際に安全性の判定ロジック・承認制約を実装しているファイル**を、追加で6件収録した。

| 追加ファイル | 由来 | 実装している安全性ロジック |
|---|---|---|
| `hypothesis_generation.py` | D-2 | `rule_based_safety_flag()`自身 |
| `static_verification.py` | E-1 | `mentions_migration()`自身 |
| `migration_review_queue_store.py` | E-4 | `record_review_decision()`のpending差し戻し拒否 |
| `code_diff_generation.py` | F-1 | `check_diff_safety()`自身——**本リストを参照する関数自体を含むファイルであり、これが弱められれば本統合全体の意味が失われるため、最優先で保護すべきと判断した** |
| `code_diff_proposal_store.py` | F-1/F-3 | `record_review_decision()`/`record_pr_outcome()` |
| `review_diff_proposals.py` | F-3 | 承認・却下への唯一のCLI入口 |

**判断根拠**: Safety-1が発見した抜け(F-3の新規ファイルが未登録だった)と、全く同じ性質のリスクは、実はF-3の3ファイルだけでなく、ゲート機能を実装している他の全ファイルに共通する構造的な問題である。依頼書の要件2は「F-3の…制御コード自体」と明示するが、この理由付けはPhaseを問わず、ゲート実装ファイル全般に等しく当てはまるため、範囲をD-2〜F-1まで一貫して広げた。一方、これらを呼び出すだけのオーケストレーション層(`code_diff_generation_runner.py`・`migration_review_queue.py`等、ゲート機能を実装していないファイル)は対象外とした——依頼書「過剰な、再設計を、避けること」に従い、「実際に安全性の判定ロジックを含むファイルのみ」という、明確で説明可能な基準に絞った。

### 6.3 統合結果の検証(実測)

元のD-2キーワード(25個)・F-1パターン(9個)が、いずれも新しい統合リストの部分集合として1件も欠落なく残っていることを、実際に集合比較して確認した。新しい統合リストは、キーワード48個・パターン18個(9機構 → 18機構への倍増、うち9件が本タスクでの新規追加)。

実際に`check_diff_safety()`を呼び出し、Safety-1が発見した抜けが解消されたことを実測した:

```
backend/app/services/diff_approval.py: blocked_safety_mechanism           (旧: passed)
backend/app/services/github_pr_publisher.py: blocked_safety_mechanism     (旧: passed)
backend/app/services/diff_patch.py: blocked_safety_mechanism              (旧: passed)
backend/app/services/code_diff_proposal_store.py: blocked_safety_mechanism (旧: passed)
backend/scripts/review_diff_proposals.py: blocked_safety_mechanism         (旧: passed)
backend/app/services/hypothesis_generation.py: blocked_safety_mechanism    (新規追加分)
backend/app/services/static_verification.py: blocked_safety_mechanism     (新規追加分)
backend/app/services/migration_review_queue_store.py: blocked_safety_mechanism (新規追加分)
backend/app/services/code_diff_generation.py: blocked_safety_mechanism    (新規追加分)
backend/app/services/orchestrator/response_guard.py: blocked_safety_mechanism (対照: 元から検出済み、回帰なし)
backend/app/services/constitution_guard.py: blocked_safety_mechanism      (対照: 同上)
backend/app/services/evidence_aggregation.py: passed                      (対照: 無関係ファイルは引き続きpassed、過剰ブロックなし)
```

### 6.4 対象外とした`_BLOCKED_FILE_PATTERNS`について

F-1には、本タスクが統合した`_SAFETY_MECHANISM_FILE_PATTERNS`とは別に、`.env`・`config.py`・`auth.py`等の機密情報・CI設定・依存関係マニフェストを対象とする`_BLOCKED_FILE_PATTERNS`が存在する。**このリストは統合の対象外とした。** 判断根拠: D-2側に対応するキーワードリストがそもそも存在せず(「.envに触れるな」に相当する自由文キーワードという概念が成立しない)、Safety-1が発見した「2箇所の重複」という問題の対象そのものではないため。依頼書「既存のD-2・F-1の判定ロジック自体は変更しないこと」の精神を、収録対象の判断にも一貫して適用した。

---

## 7. CIK分類の、正式な定義

**採用文書についての判断**: 依頼書は「`constitution.md`、または、新規の文書として」明文化することを求めている。本タスクは、`docs/sigmaris/safety_governance_report.md`(Safety-1・本タスクの成果物)を定義の正式な置き場所として採用し、`constitution.md`は編集しなかった。**判断根拠**: (a) `constitution.md`は「人間(海星さん)が直接編集する固定文書」であり(同ファイルのPhase S-4追記節)、この方針をむやみに崩したくなかったこと、(b) 依頼書自身の「報告してほしい内容」章が、CIK分類の正式な定義の記載場所として`safety_governance_report.md`を明示していること、(c) CIK分類は、Constitution本体の思想的な条項(Article 1〜9)というより、Safety-1〜3という一連の横断的なガバナンス調査のための、実務的な分類ツールという性格が強いと判断したこと。

### 7.1 正式な定義

Safety-1(2章)が示した"仮定としての解釈"を土台に、以下の通り正式に定義する。

> **Capability(能力の一線)**: シグマリスが、世界に対して実際に行使できる「権限」の範囲を規定する軸。ある機構がゲートする対象が、コード・データベース・外部システム・ファイルシステム等、現実の状態を変更する(または変更しうる)「行動」そのものである場合、この軸に分類する。
>
> **Identity(同一性の一線)**: シグマリスが、自分自身を何者として提示し、ユーザーとの関係性をどう保つかを規定する軸。ある機構がゲートする対象が、名乗る名前・トーン・距離感・依存を助長しない振る舞い等、「自己呈示・関係性の様式」である場合、この軸に分類する。
>
> **Knowledge(知識・認識論の一線)**: シグマリスが、何をどれだけの確信度で主張してよいかを規定する軸。ある機構がゲートする対象が、記憶検索の確信度・事実の整合性・引用の忠実性等、「認識的な主張の正確さ・誠実さ」である場合、この軸に分類する。

### 7.2 分類手順(曖昧なケースへの対応)

1. その機構が、**何を判定対象にしているか**(行動そのものか/自己呈示か/主張の確からしさか)を、実装(判定ロジックが実際に何を入力に取るか)から確認する。
2. 1つの軸に明確に対応する場合は、その軸に分類する。
3. **複数の軸にまたがる場合は、両方を記録し、どちらが"主"かを、実装が持つ判定ロジックの直接の対象(1次的にチェックしている内容)を基準に決める。** 例: `persona.md`10章は、「依存助長・ロールプレイの禁止」(Identity)と「確信度の低い情報の断定禁止」(Knowledge)の両方を含むが、章全体の主眼(禁止事項の大半)がIdentity寄りであるため、Identityを主、Knowledgeを従として記録する。
4. **メタな保護機構(ある機構が、他の機構"自体"を保護する場合)は、保護している対象の軸(複数になりうる)を全て記録した上で、保護を実現する仕組み自体の性質(行動のゲートかどうか)で主分類を決める。** 例: F-1〜Safety-2のブロックリストは、保護対象がIdentity・Knowledge・Capabilityの全軸にまたがるが、ブロックの仕組み自体は「コード変更という行動を止める」ものであるため、主分類はCapabilityとする。

---

## 8. 14の安全機構の、再分類結果

7章の正式な定義に基づき、Safety-1が棚卸しした表1の14件を、改めて分類し直した。**結果はSafety-1の当てはめ(2章)から変化しなかった**——Safety-1の"仮定としての解釈"が、事後的に定義した正式な基準とも一致したことを、ここで確認できたことになる。

| # | 機構 | CIK分類(正式定義による再分類) | 判定根拠(7.1の定義への当てはめ) |
|---|---|---|---|
| 1 | 名前・アイデンティティの一線(`response_guard.py`) | **Identity** | 判定対象=名乗る名前そのもの |
| 2 | 事実整合性ガード | **Knowledge** | 判定対象=応答内の主張が事実(ツール出力)と一致するか |
| 3 | B11(校正された放棄判定) | **Knowledge** | 判定対象=記憶検索結果への確信度 |
| 4 | Self-Critique(G-3) | **Knowledge** | 判定対象=応答とEvidenceの整合性 |
| 5 | Citation Audit(G-4) | **Knowledge** | 判定対象=claim単位の引用の忠実性 |
| 6 | 制止する時のルール(persona.md 9章) | **Identity**(主)/関係性 | 判定対象=反対の伝え方という関係性の様式 |
| 7 | 禁止事項(persona.md 10章) | **Identity**(主)、**Knowledge**(従) | 依存助長・ロールプレイ禁止=Identity、確信度の低い情報の断定禁止=Knowledge(7.2節の曖昧ケース) |
| 8 | Constitution・Capability一線 | **Capability** | 判定対象=コード変更・DB変更・外部投稿等の行動 |
| 9 | D-2 `requires_special_review` | **Capability** | 判定対象=将来Capability一線に触れうる行動の"種"(仮説) |
| 10 | E-1 マイグレーション検出 | **Capability** | 判定対象=DB構造変更という行動 |
| 11 | E-4 マイグレーションレビューキュー | **Capability** | 判定対象=DB構造変更の実行可否 |
| 12 | F-1〜Safety-2 ブロックリスト(`safety_critical_files.py`) | **Capability**(主)、保護対象はIdentity/Knowledge/Capability全軸 | 判定対象=コード変更という行動そのもの。保護している中身は#1〜11の全軸にまたがる(7.2節のメタ機構ケース) |
| 13 | F-1〜F-3 承認フロー全体 | **Capability** | 判定対象=コード変更の実行可否 |
| 14 | F-3 二重チェック | **Capability** | 同上 |

**分類の分布**: Capability 8件、Knowledge 4件、Identity 2件(#7は2軸にまたがるためIdentityとKnowledge両方にカウント)。Safety-1の考察通り、Capabilityが最多——Phase D〜Fが「行動」を伴う自己改善パイプラインの構築に集中していた時期であることと整合する。

---

## 9. 今後の、リストの更新忘れを、防ぐための、運用ルールの提案

依頼書「複雑な自動化の仕組みでなくてよい」との指示に従い、以下の2点を組み合わせた、軽量な仕組みを提案する。

### 9.1 運用ルール(人間向け、ドキュメントベース)

今後のPhase(自己改善パイプラインに関わるもの: D・E・F系列、および将来のSafety系列)の完了報告に、次のチェック項目を1行加えることを提案する:

> **「本Phaseで新設・変更したファイルのうち、安全性の判定ロジック・承認ゲート・確信度制御等を実装するものはあるか? あれば、`backend/app/services/safety_critical_files.py`の`SAFETY_CRITICAL_FILES`へ追加し、追加した判断根拠を報告書に明記すること。」**

これは、今回のタスク自体が辿った手順(Safety-1で発見 → Safety-2で対応)を、次回以降は都度の完了報告の中で先回りして確認する、という運用上の習慣化であり、新しい仕組みの実装を必要としない。

### 9.2 機械的な補助(すでに実装済み、6.3節で述べた検証の一部として恒久化)

`SAFETY_CRITICAL_FILES`に登録された各エントリが、実際にリポジトリ上に存在するファイルを指しているかを検証する、軽量なテストを新設した(`RegistryFreshnessTests::test_every_registered_file_actually_exists_in_repo`、10章参照)。**これは「リネーム・削除されたのに登録が残ったままの、古いエントリ」というドリフトの片方向のみを検出する**——「追加登録されるべき新しいファイルが、まだ登録されていない」という、より重要な逆方向のドリフトは、ファイル存在チェックという機械的な手段だけでは原理的に検出できない(「安全性に関わるかどうか」の判断は人間の意味理解を要するため)。この逆方向は、9.1節の運用ルールで補うほかない、という限界を正直に記録する。

---

## 10. テスト結果

`test_safety_2_list_consolidation.py`として10件の新規テストを作成した(scratchディレクトリ)。

```
SharedListStructureTests (4件)
  PASS: hypothesis_generation.pyのキーワードが、safety_critical_files.py
        由来であること(オブジェクト等価性の直接検証)
  PASS: code_diff_generation.pyのパターンが、同上
  PASS: SAFETY_CRITICAL_FILESに重複したnameが無いこと
  PASS: 全エントリが、keywords・file_patternの両方を持つこと

OriginalNineMechanismsPreservedTests (2件、依頼書「判定ロジック自体は
  変更しない」への直接対応)
  PASS: 【重要】元の25個のキーワードが、統合後も1件も欠落していない
        (集合演算による直接検証)
  PASS: 【重要】元の9個のファイルパターンが、同上

F3AndPipelineGateFilesNowProtectedTests (3件、依頼書の要件1・2への
  直接対応)
  PASS: 【最重要】diff_approval.py・github_pr_publisher.py・diff_patch.py・
        code_diff_proposal_store.py・review_diff_proposals.py・
        hypothesis_generation.py・static_verification.py・
        migration_review_queue_store.py・code_diff_generation.pyの
        9ファイル全てが、check_diff_safety()で正しくblocked_safety_
        mechanismと判定されること(Safety-1が発見した抜けの解消の実測)
  PASS: 無関係なファイル(evidence_aggregation.py)は引き続きpassed
        (過剰ブロックが発生していないことの回帰確認)
  PASS: D-2側(rule_based_safety_flag())でも、hypothesis_generation.py
        自身への言及が、自由文キーワード一致で検出できること

RegistryFreshnessTests (1件、9.2節の運用ルール補助の一部)
  PASS: 登録された全エントリが、実際にリポジトリ上に存在するファイルを
        指していること

10 passed
```

既存の`backend/tests/`・D-2〜Safety-1の全scratchテスト一式を再実行し、リグレッションが無いことを確認した。**唯一、F-1の`CheckDiffSafetyTests::test_diff_touching_unexpected_file_blocked`が、統合直後に1件失敗した**——これは判定ロジックの回帰ではなく、このテストが「安全機構リストに含まれない、無関係なファイル」の一例として`hypothesis_generation.py`を`expected_target_file`に使っていたところ、本タスクの意図通りの変更(6.2節)によって、そのファイル自体が安全機構ファイルに"格上げ"されたことによる、テストフィクスチャの偶発的な衝突だった。判定ロジック自体は変更していないため、`expected_target_file`を、安全機構リストに含まれない別の無関係ファイル(`hypothesis_prioritization.py`)へ差し替える、テストのみの1行修正で解消した(判断根拠、依頼書「既存のD-2・F-1のテストが引き続き通ることを確認する」への対応として、テスト意図を保ったまま最小限の修正にとどめた)。

```
10(本タスク) + 505(既存、F-3まで) = 515 passed, 7 subtests passed(合算実行)
```

**実モデルAPI・実データベースでの検証は行っていない。** 本タスクはPythonの定数リストの統合のみであり、マイグレーションを必要としない(DBスキーマ変更なし)。

---

## 11. 気づいた懸念点・次のステップ(Safety-3: 異常検知・監視の強化)に向けた申し送り事項

1. **9.2節で述べた通り、「新しく追加登録されるべきファイルが、まだ登録されていない」という、より本質的な方向のドリフトは、機械的には検出できない。** Safety-3(異常検知・監視の強化)が、この限界に対処する仕組み(例: 新規ファイル作成を伴うコミットで、ファイル冒頭のコメントに"安全機構"related語彙があるかを検知する、軽量なヒューリスティック等)を検討する価値があるかもしれないが、過剰な自動化にならないよう慎重な設計が必要だと考える。
2. **6.2節の判断で、収録対象を9ファイルへ拡張したが、この基準(「実際に安全性の判定ロジックを含むファイル」)自体の线引きは、本タスクの独自解釈である。** 今後、自己改善パイプラインにさらにファイルが追加された場合(Safety-3以降で新設されるファイルを含む)、同じ基準を機械的に適用できるとは限らない——最終的には、9.1節の運用ルールに基づく人間の判断が必要になる場面が、引き続き残る。
3. **7章でCIK分類を`safety_governance_report.md`に定義したが、`constitution.md`本体には反映していない。** 海星さんが、CIK分類をConstitution本体の一部として正式に位置づけたい場合は、別途、`constitution.md`への追記を検討する余地がある(本タスクでは、7章で述べた判断根拠により、あえて見送った)。
4. **表1の14機構のうち、#7(persona.md 10章)のみが2軸にまたがる、という状況は、Safety-1・Safety-2を通じて変わっていない。** これは欠陥ではなく、`persona.md`10章自体が複数の関心事(依存助長禁止・確信度の断定禁止)を1つの章にまとめている、既存文書の構成に起因するものであり、Safety-3以降でこの章を分割する等の変更は、`persona.md`自体の編集を伴うため、本タスクのスコープ外とした。
5. **Safety-1が「その他の抜け」として記録した`sigmaris_self_discrepancies`の未配線状態(3.1節)は、本タスクでは対応していない。** Safety-1の提案3として申し送られたままであり、引き続きSafety-3以降の検討課題として残る。

---

# Safety-3 実施報告: 異常検知・監視の強化(安全性・ガバナンスの柱、最終ステップ)

**作業ブランチ:** `safety-3-anomaly-detection-monitoring`(mainから新規作成)
**範囲:** Safety-2が申し送った、根本的なリスク(「新しく追加された、安全上重要なファイルが、リストに反映されないまま放置される」)への、正式な対応。Phase RのRC-5(循環破損の自動検知)が既に確立している考え方を最優先で検討・応用し、新しい重量級の監視基盤はゼロから作らなかった。これをもって、安全性・ガバナンスの柱(Safety-1〜Safety-3)全体が完了する。

---

## 12. 追加漏れの、検知の仕組みの、実装内容(要件1・2)

### 12.1 新設モジュール: `backend/app/services/safety_critical_files_scan.py`

依頼書が例示した「ゲート・チェックの実装パターンを持つ新しいファイルを検出する」を、**D-2の`rule_based_safety_flag()`と全く同じ設計思想(2種類のシグナルのOR結合、安全側に倒す)**で実装した——新しい判定方式を作らず、既存資産(D-2)をそのまま横展開した(依頼書「既存資産の再利用を最優先する」への直接対応)。

- **シグナルA(関数名パターン)**: `check_diff_safety`・`rule_based_safety_flag`・`requires_approval`・`record_review_decision`・`mentions_migration`・`classify_confidence_tier`・`evaluate_executive_gate`等、既存の安全機構(Safety-1・Safety-2で棚卸し済み)が実際に使っている関数名から抽出した、安全・承認・レビュー判定に特有の語彙のみをマーカーとした。
- **シグナルB(ファイル冒頭コメント)**: このコードベース一貫の慣習(全サービスファイルが`# 役割: ...`で始まる)を利用し、冒頭40行に「安全機構」「承認フロー」「review_status」等のキーワードが含まれるかを確認する。

**判断根拠(単純な`check_`接頭辞を採用しなかった理由)**: 当初、関数名の`check_`接頭辞のみで判定する案を検討したが、これは`cycle_health_metrics.py`(RC-2)の`check_chat_message_order()`・`check_event_facts_against_experiences()`という、安全機構ではない既存関数を過検知することが、実装時の実測で判明した。そのため、安全・承認判定に特有の、より狭い語彙のみをマーカーとして採用した——実際にRC-2の関数群が過検知されないことを、テストで直接確認済み(15章参照)。

**デコレータベースの検出は実装していない**: 依頼書は「特定のデコレータ等」も例示していたが、このコードベースには、安全性判定に使われるデコレータが1つも存在しないことを確認した(全ての既存機構が、素の関数呼び出しとして実装されている)。存在しないパターンを検出する仕組みを作る必要はないと判断し、将来デコレータベースの実装が導入された場合に、マーカーを追加拡張できる設計(シグナルの追加が容易な構造)にとどめた。

### 12.2 検出結果の、`safety_critical_files.py`との突合

`find_unregistered_gate_files()`が、シグナルA・Bのいずれかに一致した全ファイルを、Safety-2の`get_safety_mechanism_file_patterns()`(正典)と突合し、どちらの正規表現にも一致しないものを「未登録候補」として返す。**この関数は、`SAFETY_CRITICAL_FILES`への書き込みを一切行わない**(要件2「完全な自動化ではなく、人間への通知に留める」への直接対応)。

### 12.3 新設CLI: `backend/scripts/scan_safety_critical_files.py`

読み取り専用(DB書き込みなし、ファイル書き込みなし)。実際にこのリポジトリに対して実行した結果は以下の通り(実測、レポート執筆時点):

```
スキャン対象ファイル数: 140
ゲートらしいパターンに一致したファイル数: 19
うち、safety_critical_files.pyに未登録: 3

  - backend/app/services/goal_proposal.py
      理由: 冒頭コメントがマーカー「constitution_guard」に一致
  - backend/app/services/migration_review_queue.py
      理由: 冒頭コメントがマーカー「review_status」に一致
  - backend/scripts/run_migration_review_queue.py
      理由: 冒頭コメントがマーカー「review_status」に一致
```

**この3件について、実際に確認した結果(判断根拠)**: いずれも、安全機構"自体"を実装しているファイルではなく、既存の安全機構(`constitution_guard.py`・`migration_review_queue_store.py`)を**呼び出すだけ**のオーケストレーション層である——Safety-2(6.2節)が確立した「実際に安全性の判定ロジックを含むファイルのみ登録する」という基準に照らすと、この3件は**登録すべきでない**、というのが本タスクの判断である。**あえてこの3件を`SAFETY_CRITICAL_FILES`へ追加しなかった**——これは、スキャナーが意図通り「安全側に倒して、やや広めに候補を挙げる」ヒューリスティックであり、最終判断は常に人間が行う、という設計思想を、実際のデータで裏付ける結果になった(判断根拠、要件2の実例としてそのまま記録する)。海星さんが、これらのファイルもリストに含めるべきと判断する場合は、`safety_critical_files.py`への追記を検討してほしい。

---

## 13. Phase RのRC-5との、統合内容(要件3)

### 13.1 統合方法

`cycle_health_runner.py::run_cycle_health()`(RC-1〜RC-5を計測する、既存の関数)に、Safety-3のスキャン(`find_unregistered_gate_files()`)を追加のステップとして組み込んだ。結果は、RC-1〜RC-5と同じ戻り値dict・同じ`sigmaris_cycle_health_runs`テーブル(追加マイグレーション`202608030061_cycle_health_runs_safety_governance.sql`、`safety_governance_status`・`safety_governance_unregistered_count`の2列を追加)・同じCLI(`scripts/run_cycle_health.py`)を通じて、運用者に提示される。**新しい定期実行の仕組み・新しい記録テーブルは、一切作っていない**(依頼書「既存資産の再利用を最優先する」への直接対応)。

### 13.2 RC-5の仕組みを、そのまま流用しなかった判断根拠(独断で決めた箇所)

RC-5(`detect_cycle_break()`)は、「過去の実行群の平均(baseline)と、今回の値の差が、閾値を超えたら異常」という、履歴比較方式を採用している。本タスクでも、この方式(`check_metric_drop()`、Phase D-1で汎用化済みの公開関数)を直接再利用できないか、依頼書の指示通り最優先で検討した。

**検討した結果、直接の再利用は見送った。** 判断根拠: RC-5方式は「未登録ファイル数 ÷ 検出済みファイル総数」のような**比率**を指標として扱う必要があるが、この比率は、正典(`SAFETY_CRITICAL_FILES`)の総エントリ数が増えるほど、1件の未登録漏れが比率上希釈される——例えば、登録済み18件+未登録1件なら比率は`18/19=0.947`であり、baseline(過去の平均、通常1.0付近)からの低下幅は`0.053`程度にしかならず、RC-5の`drop_threshold=0.2`を到底超えない。**登録リストが将来さらに大きくなるほど、この検出方式は感度が下がっていく**、という構造的な弱点があると判断した。加えて、この種の抜けは「1件でもあれば、その時点で即座に気づくべき」性質のものであり(RC-1/RC-2のような、日々のノイズを許容すべき連続的な品質指標とは異なる)、過去の実行群との比較を待つ必要がない——**むしろ即座に判定できることの方が、依頼書の目的(人間への気づきの提供)に適う**、と判断した。

**採用した方式**: 履歴を必要としない、瞬間的な構造チェック(「今この瞬間、未登録候補は0件か」)を直接採用した。RC-5の3値ステータス(`insufficient_history`/`healthy`/`break_detected`)のうち、`insufficient_history`に相当する状態は、本チェックには存在しない(常に判定可能なため)——そのため、`healthy`/`gap_detected`の2値ステータスとした。**RC-5の"考え方"(閾値ベースのシンプルな判定、機械学習を使わない)は踏襲しつつ、"具体的な比較方式"(履歴平均との差分)は、この種の異常の性質に合わせて適応させた**、という判断を、正直に記録する。

### 13.3 通知への統合(RC-5と同じ判断根拠で見送り)

RC-5が15.4節(既存)で見送った判断根拠(通知が未検証のまま有効化すると誤報リスクがある、`run_cycle_health.py`自体が定期実行されていない)は、本チェックにも同様に当てはまるため、通知の実装は同じ理由で見送った。`get_notifier().send(...)`がいつでも統合できる状態にあることも、RC-5と同じ状態を維持している。

---

## 14. 自由度への、過剰な制限が、ないかの、確認結果(要件5、S-4と同じ観点)

S-4(`phase_s_report.md` 28.2節)が確認したのと同じ観点——「日常の自由な判断・行動(S-0〜S-3)を、過剰に制限していないか」を、Safety-1〜Safety-3全体について、改めて確認した。

**S-0〜S-3(Drive System・Executive Gate・Goal Proposal・異論表明)への影響は皆無であることを確認した。** Safety-1〜3のいずれの変更も、これらのモジュールに一切触れていない。

**Safety-3自体(スキャナー・RC-5統合)も、いかなる行動もブロックしない。** 読み取り専用であり、`SAFETY_CRITICAL_FILES`への自動追加も、承認フローへの介入も行わない——依頼書の制約通り、人間への気づきの提供のみに留まる。

**一方、以下の1点は、正直に「制約が増えた」ケースとして記録する(依頼書「もし過剰な制約が見つかった場合、報告に明記すること、修正しなくてよい」への対応):**

Safety-2(6.2節)が、`safety_critical_files.py`の収録対象を、依頼書が明示した3ファイルから、自己改善パイプライン自身のゲート実装ファイル9件へ拡張したことで、これら9件を対象にした差分提案は、`code_diff_generation.py::check_diff_safety()`によって、生成された瞬間に`review_status="rejected"`として即座に破棄されるようになった(F-1の設計、`blocked_safety_mechanism`は`pending`に一切至らない)。

**これは、`response_guard.py`・`constitution_guard.py`等、S-4以来の「最後の砦」ファイルに対しては、意図通りの挙動である**(これらのファイルへの変更提案は、内容を精査するまでもなく一律拒否すべき、という判断が既に確立している)。**しかし、Safety-2で新規追加した9件のうち、`hypothesis_generation.py`・`static_verification.py`・`code_diff_generation.py`等は、自己改善パイプライン自身の"通常のコード"でもある**——例えば、「`static_verification.py`の`_MIGRATION_KEYWORDS`に、見落としていたキーワードを1つ追加する」というような、安全機構を弱める意図が全くない、純粋な改善提案であっても、`blocked_safety_mechanism`によって、人間の目に触れることなく自動的に`rejected`として記録されてしまう(`review_diff_proposals.py list`は`pending`のみを表示するため、この却下は運用者からは見えにくい)。

**Safety-2の時点では「多層防御を最優先する」という判断でこの設計を選んだが、振り返ると、これは「安全機構自体への変更を一律拒否する」ことと「安全機構"に関連する"ファイルへの、無害な改善提案まで一律拒否する」ことを、区別できていない、過剰な制約だと言える。** 本タスクでは、依頼書の指示通り、修正は行わない。**Safety-4以降の候補として、以下を提案する**: `blocked_safety_mechanism`を、`response_guard.py`等の「絶対拒否すべきファイル」と、Safety-2で追加した「拒否ではなく、より慎重な人間レビューを促すべきファイル」の、2段階に分ける(例えば、後者は`review_status="pending"`のまま、`requires_extra_caution=true`のようなフラグを別途立てて、`review_diff_proposals.py show`で強調表示する等)——これにより、多層防御を維持しつつ、正当な改善提案が握りつぶされる過剰な制約を解消できる可能性がある。

---

## 15. テスト結果

`test_safety_3_anomaly_detection.py`として11件の新規テストを作成した(scratchディレクトリ)。

```
ScanAgainstRealRepoTests (3件、実際のbackend/への直接検証)
  PASS: 【重要】cycle_health_metrics.py(RC-2のcheck_関数群)が、過検知
        されないこと(12.1節のマーカー選定判断の直接検証)
  PASS: 登録済みの全ファイルが、未登録候補リストに含まれないこと
  PASS: スキャンが完了し、妥当な件数を返すこと

SyntheticUnregisteredFileDetectionTests (4件、依頼書のテスト要件への
  直接対応: 意図的に新しいファイルを作成し、検知を確認する)
  PASS: 【最重要】ゲートらしい関数名(check_new_thing_safety)を持つ
        新規ファイルが、未登録候補として検知されること
  PASS: 【最重要】ゲートらしい冒頭コメント(安全機構、review_status)を
        持つ新規ファイルが、検知されること
  PASS: ゲートらしいマーカーを一切持たない、普通のファイルは検知
        されないこと(過剰検知の防止確認)
  PASS: scan_for_gate_pattern_files()単体(正典との突合前)の直接検証

RegistryStillCorrectlyExcludesSelfTests (1件)
  PASS: スキャナー・正典モジュール自身が、自己参照で誤検知されないこと

CycleHealthIntegrationTests (1件、依頼書の要件3への直接対応)
  PASS: 【重要】run_cycle_health()の戻り値にsafety_governanceセクションが
        含まれ、実際のリポジトリに対するスキャン結果を反映していること

RecordCycleHealthRunPayloadTests (2件)
  PASS: safety_governanceの内容が、正しいペイロード形状でDBへ送信
        されること
  PASS: safety_governance未指定時、両列がNoneになること(後方互換性)

11 passed
```

既存の`backend/tests/`・Safety-2までの全scratchテスト一式(Phase R系テストを含む)を再実行し、リグレッションが無いことを確認した。**Phase Rの既存テスト(37件、RC-2・RC-3統合テストを含む)は、1件も変更せずに、そのまま全てパスした**——`run_cycle_health()`への統合が、既存のRC-1〜5計測ロジックに一切影響を与えていないことの直接証明。

```
11(本タスク) + 515(既存、Safety-2まで) = 526 passed, 7 subtests passed(合算実行)
```

**実モデルAPI・実データベースでの検証は行っていない。** `run_cycle_health()`統合テストは、既存のRC-1〜5計測と同じ理由でDB呼び出しをモックしているが、**Safety-3のスキャン自体(`find_unregistered_gate_files()`)は、モックなしで実際の`backend/`ツリーに対して実行し、実測結果(12.3節)を得た**——ファイルシステムの読み取りのみで完結するため、実データ・実APIが無くても、本番同等の検証ができている。マイグレーション(`202608030061_cycle_health_runs_safety_governance.sql`)は作成のみ、適用は運用者側に委ねる。

---

## 16. 安全性・ガバナンスの柱、全体(Safety-1〜Safety-3)を通じての、振り返り・残っている懸念事項の総まとめ

### 16.1 何が確立されたか

Safety-1(棚卸し)→ Safety-2(統合・CIK正式定義)→ Safety-3(異常検知・監視)という3段階を通じて、Phase A〜Fにわたって別々に実装されてきた14の安全機構が、初めて1箇所で可視化され、構造的な弱点(2箇所独立ハードコードによる更新漏れリスク)が発見・解消され、**その解消策自体が将来も陳腐化しないよう、軽量な監視の仕組みまで整備された。**

- **Safety-1**: 14機構の役割・トリガー条件・対象範囲を一覧化し、CIK分類への暫定的な当てはめを行った。コード変更は一切行わず、実際に`check_diff_safety()`を呼び出して「F-3の新規ファイルが未検出になる」という具体的な抜けを実測で発見した。
- **Safety-2**: 発見された抜けを、単一の正典(`safety_critical_files.py`)への統合で解消した。収録対象を、依頼書が示した3ファイルから、自己改善パイプライン自身のゲート実装ファイル9件へ、判断根拠を明記した上で拡張した。CIK分類を正式に定義し、14機構を再分類した(結果はSafety-1の暫定解釈と一致)。
- **Safety-3**: Safety-2が申し送った「新しい追加漏れが今後も起こりうる」という根本的なリスクに対し、D-2の既存パターン(キーワードOR結合)を踏襲したヒューリスティックなスキャナーを実装し、Phase RのRC-5が確立した測定基盤(同じテーブル・同じCLI)に統合した。実際にこのリポジトリをスキャンし、3件の(登録すべきでないと判断した)候補を発見・記録した。

### 16.2 一貫して守られた設計原則

1. **新しい重量級の仕組みを、一度も作らなかった。** Safety-2はD-2/F-1の既存ハードコードリストを統合しただけ、Safety-3はD-2のOR結合パターン+RC-5の測定基盤をそのまま応用しただけである。3タスクを通じて、真に新規のロジックは「ファイルパスの正規化・突合」という、最小限の接着コードのみだった。
2. **完全な自動化を、意図的に避け続けた。** Safety-2のリスト統合は値の同期のみ(判定ロジックは変更しない)、Safety-3のスキャナーは検知のみ(自動追加はしない)——いずれの段階でも、最終判断は常に人間に残した。
3. **「できていないこと」を、正直に記録し続けた。** Safety-1の「CIK分類の正式な定義がリポジトリに存在しない」という告白、Safety-2の「逆方向のドリフト(新規ファイルの登録漏れ)は機械的に検出できない」という限界の明記、Safety-3の「3件の候補を、あえて登録しなかった」という判断——いずれも、過大な達成を主張せず、限界を明示することを優先した。
4. **S-4が確立した「最後の砦であり、日常の検閲官ではない」という運用原則を、3タスクを通じて一度も破らなかった。** S-0〜S-3の自由な判断・行動には、Safety-1〜3のいずれも一切触れていない。14章で記録した「過剰な制約」も、S-0〜S-3ではなく、あくまでD〜Fの自己改善パイプライン内部の、限定された範囲にとどまる。

### 16.3 残っている懸念事項(総まとめ)

1. **【最重要、14章で新規発見】Safety-2で追加した9件のうち、自己改善パイプライン自身の"通常のコード"を含む複数ファイルへの、無害な改善提案が、`blocked_safety_mechanism`によって、人間の目に触れることなく自動的に却下されている。** Safety-4以降で、「絶対拒否」と「慎重レビューを促す」の2段階化を検討する価値がある(14章、判断根拠含め詳述)。
2. **逆方向のドリフト検知の限界(Safety-2の9.2節、Safety-3の12章)は、今回のスキャナーでも完全には解消されていない。** ヒューリスティック(関数名・冒頭コメント)に依存するため、命名規則に従わない新しいゲートは、依然として見逃されうる。9.1節の運用ルール(人間による確認)が、最後の砦として残り続ける。
3. **Safety-3が発見した3件の候補(`goal_proposal.py`・`migration_review_queue.py`・`run_migration_review_queue.py`)は、本タスクの判断で登録を見送ったが、海星さんが異なる判断をする可能性がある。** 12.3節の判断根拠を確認の上、必要であれば`safety_critical_files.py`への追記を検討してほしい。
4. **通知の実装(RC-5・Safety-3のsafety_governanceいずれも)は、一貫して見送られたままである。** `run_cycle_health.py`自体が定期実行されていない(手動CLIのまま)ため、「検知はしたが誰も見ない」状態が、Phase R-3から変わらず続いている——これは、Safety-1〜3ではなく、Phase Rの運用設計(定期実行の仕組み)の課題として、引き続き申し送る。
5. **CIK分類(Safety-2 7章)は、`safety_governance_report.md`にのみ定義されており、`constitution.md`本体には反映されていない。** 海星さんが、この分類を正式にConstitutionの一部としたい場合は、別途の判断が必要になる。
6. **本タスクを含め、Safety-1〜3を通じて、実際のGitHubリポジトリ・実データベースに対する、エンドツーエンドの動作確認は一度も行われていない。** 全ての検証は、モックまたは実際のファイルシステムに対する読み取り専用の検証にとどまる——これはPhase D〜Fの完了時と同じ、意図的な制約である。運用者が、実際の環境で`scripts/scan_safety_critical_files.py`・`scripts/run_cycle_health.py`を一度実行し、想定通りに動作することを確認することを推奨する。

---

## 17. マージについて

「テスト・検証」章の要件をすべて満たしていることを確認した(意図的に作成した未登録ファイルの検知・既存テストの回帰確認、いずれも15章参照)。既存機能(Safety-1・Safety-2・D・E・F全体・Phase R・Phase G・Phase S・B群全体)への悪影響も、全テスト再実行によって確認した。依頼書の指示通り、確認を待たずmainへマージ・プッシュする。
