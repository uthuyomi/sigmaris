# Phase F-1 実施報告: 仮説からコード差分への変換(承認必須、コミットは行わない)

**作業ブランチ:** `phase-f1-code-diff-generation`(mainから新規作成)
**範囲:** D-3で優先順位付けされ、E-1で検証された仮説から、LLMに統一diff形式のコード差分を生成させ、機械的な安全性チェックを経て、承認待ちとしてDBへ保存する仕組みの実装。**実際にGitへコミット・ブランチ作成・プルリクエスト提出する処理は、一切実装していない。** 依頼書の指示通り、テストが全て通過した現時点でも、mainへは一切マージせず、本報告を提示した上で運用者の確認を待つ。

---

## 0. 前提として確認したこと

- `docs/sigmaris/phase_e_report.md`(Phase E全体): E-2が確認した「仮説→コード差分の変換は、Phase Fの仕事」という結論、E-1のカバレッジ照合(`matched_modules`)の仕組み
- `docs/sigmaris/phase_d_report.md`(D-2・D-3): 仮説の構造(`title`/`what_is_problem`/`why_problem`/`how_to_improve`)、D-3の`build_phase_e_handoff()`が`target_files`を常に`None`のプレースホルダとして残していたこと
- `docs/sigmaris/constitution.md` Article 6: 「コードの変更」が承認必須リストに含まれること、`constitution_guard.py`の`CAPABILITY_APPROVAL_REQUIRED_CATEGORIES`に`"code_change"`が既に定義されていること(コメントに「将来Phase D以降」と明記されていた)

---

## 1. コード差分生成の実装詳細

新設: `backend/app/services/code_diff_generation.py`(生成ロジック・安全性チェック、I/Oなし)・`code_diff_generation_runner.py`(候補選定・ファイル読み取り・オーケストレーション)・`code_diff_proposal_store.py`(永続化)。既存の3層分離パターンを踏襲した。

### 1.1 対象範囲の絞り込み(方針1、判断根拠)

**入力の絞り込み**: `sigmaris_static_verifications`(E-1)の`verdict="baseline_healthy_with_coverage"`のみを対象とした。

**判断根拠(4つのE-1判定のうち、この1つだけを採用した理由)**: E-1の判定は`excluded_migration`/`baseline_unhealthy`/`insufficient_signal`/`baseline_healthy_with_coverage`の4種類あるが、実際に「コードの差分を生成する」という、これまでで最も踏み込んだ行動の入力として使えるのは、**既存テストのカバレッジが実際に確認されている`baseline_healthy_with_coverage`だけ**だと判断した。`insufficient_signal`(判断材料が無い)を入力にすると、生成した差分が既存の安全網(テスト)に一切引っかからない領域を触ることになり、依頼書が求める「安全な仮説のみを対象に」という要件2に反すると考えた。

**「E-1・E-2を通過した仮説」という依頼書の表現について、正直に記録する重要な限界**: 依頼書は「D-3で優先順位付けされ、E-1・E-2の検証を通過した仮説」と述べているが、調査の結果、**E-2は個々の仮説の内容を検証する設計になっていない**ことを確認した(`sandbox_verification_runner.py::_get_candidate_hypothesis_ids()`は、E-1の`insufficient_signal`判定の仮説idを、あくまで参考情報として一覧するだけであり、`baseline_healthy_with_coverage`の仮説は最初からE-2の対象にすら入っていない)。つまり、「E-1を通過し、かつE-2も通過した」という仮説の集合は、現在の設計上、**存在しない**(E-1のbaseline_healthy_with_coverage群とE-2のcandidate群は、互いに素な集合)。

この矛盾に直面し、以下のいずれかを選ぶ必要があった。

- 案A: `baseline_healthy_with_coverage`(E-1の最良の判定)のみを要求し、E-2の関与は求めない
- 案B: E-2の`candidate_hypothesis_ids`(=E-1で`insufficient_signal`だった仮説)を対象にする
- 案C: E-1・E-2の統合が未整備であること自体を理由に、本タスクを一旦停止し、報告する

**案Aを採用した。** 判断根拠: 案Bは、依頼書自身が「target_filesが明確な仮説だけを対象とする」ことを求めているのと矛盾する——`insufficient_signal`はまさに「対象領域の情報が乏しい」仮説群であり、コード差分という最も具体的な提案の入力には適さない。案Cは、依頼書の「絶対原則に反する可能性に気づいたら報告する」の対象は「コミットしてしまう経路」であり、この設計上の未整合はその種類の問題ではないと判断し、停止するほどの事態ではないと考えた。**この判断自体を、次章で述べる「E-1・E-2検証環境との統合」(F-2)への、最重要の申し送り事項として記録する。**

### 1.2 target_filesの欠落を、E-1のmatched_modulesで補う(方針1、依頼書が検討を求めた論点)

依頼書は「target_filesが明確な仮説だけを対象とする」ことを検討するよう求めていたが、調査の結果、**D-3の`build_phase_e_handoff()`が組み立てる`target_files`は、常に`None`の未設定プレースホルダである**ことを確認した(D-2の生成プロンプトが対象ファイル名を出力させていないため)。これを字義通り要求すると、**対象仮説が恒久的に0件になる。**

代わりに、**E-1(`static_verification.py`)が既に算出済みの`matched_modules`**(仮説の文面から推定され、かつ既存テストのカバレッジと実際に一致することが確認済みのモジュール名)を、`target_files`の実質的な代替として採用した。判断根拠は、単なる代替ではなく、依頼書が求める「target_filesが明確」という条件を、より安全な形で満たすと考えたため——`matched_modules`は「推定されただけ」ではなく「既存テストのカバレッジと一致することまで確認済み」の情報であり、`target_files`(仮に実装されても、あくまで仮説生成時のLLMの推定にとどまる)より高い確度を持つ。

1つの仮説につき、`matched_modules[0]`(最初に一致したモジュール)のみを対象とし、実際のファイルパスは`code_diff_generation_runner.py::resolve_module_path()`(`backend/app/`配下を、モジュールのベース名で検索、読み取り専用、一致が複数または0件の場合はNone)で解決した。

### 1.3 生成対象の範囲(方針1「単一ファイル」への対応)

`resolve_module_path()`が単一のファイルしか返さないため、生成される差分は構造的に単一ファイルに限定される。加えて、生成プロンプト自体にも「変更は、示された1ファイルの中に完結させ、他のファイルへの変更は含めないでください」と明記し、**指示と、1.4節で述べる機械的な検証の、二重の担保**にした。

対象ファイルの内容が12,000文字を超える場合は、生成自体を見送る(`MAX_FILE_CHARS_FOR_DIFF`)。判断根拠: 大きなファイルの一部だけをプロンプトに切り詰めて渡すと、LLMが実際には存在しない周辺コードを幻視して不正確なdiffを生成するリスクが高まる。無理に生成させるより、「対象ファイルが大きすぎる」という明示的な結果にとどめる方が安全、というD-2の`is_vague_or_unsupported()`と同じ「無理をしない」設計を踏襲した。

### 1.4 モデル階層(依頼書の制約への対応)

`TaskType.CODE_DIFF_GENERATION`を新設し、D-2の`HYPOTHESIS_GENERATION`と**同じadvanced tierへルーティング**した(`_openai_model_for_task()`の同じ判定グループに追加)。新しいモデル階層は追加していない。ローカルLLM(Ollama)にはルーティングしない設定にした——`HYPOTHESIS_GENERATION`と同じ判断根拠(品質が重要で、レイテンシに制約が無いオフラインCLI)。

`HYPOTHESIS_GENERATION`を直接再利用せず、新しいTaskType値にした判断根拠: 入力(仮説+対象ファイルの実際のソースコード)・出力形状(統一diffテキスト、JSON検証済み仮説ではない)が明確に異なる契約であり、「1つの分類関心につき1つのTaskType」という、このコードベース一貫の前例に従った。

---

## 2. 安全性チェックの実装内容(要件4)

`code_diff_generation.py::check_diff_safety()`(LLM呼び出しなし、機械的な照合のみ)。判定の優先順位は以下の通り。

1. **機密ファイルへの変更**(`blocked_sensitive_file`): 旧`self_improvement.py`(削除済み)が持っていたブロックリストの考え方を、そのまま再利用した(`.env`・`secret`・`credential`・`password`・`.pem`/`.key`等の鍵ファイル・`auth.py`/`jwt_manager.py`/`config.py`/`settings.py`・`.github/`・`requirements*.txt`/`pyproject.toml`・`package*.json`・`dockerfile`/`docker-compose`/`nginx.conf`)
2. **Constitution/S-4の安全機構ファイルへの変更**(`blocked_safety_mechanism`): D-2の`rule_based_safety_flag()`が使ったのと同じキーワード源(S-4の「最後の砦」棚卸し結果、`docs/sigmaris/phase_s_report.md` 28.1節)を、今回は"仮説の文章"ではなく"生成された差分の対象ファイルパス"に対して適用した——`response_guard.py`・`memory_confidence.py`・`constitution_guard.py`・`self_critique.py`・`citation_audit.py`・`dissent.py`・`executive_gate.py`・`persona.md`・`constitution.md`
3. **意図しない対象ファイルへの変更**(`blocked_unexpected_target`): 生成された差分の`+++ b/<path>`行を全て抽出し(`extract_diff_target_paths()`)、依頼した対象ファイル以外が含まれていないかを確認する。1.3節で述べた「1ファイルに限定する」というプロンプト指示自体を、機械的にも検証する——LLMが指示を逸脱した兆候を、内容を精査せず一律で拒否する設計
4. 上記いずれにも該当しない場合のみ `passed`

**「Constitution違反に該当しないか」の、もう1つの側面(要件4後半)**: `constitution_guard.requires_approval("code_change")`は、`CAPABILITY_APPROVAL_REQUIRED_CATEGORIES`に`"code_change"`が既に含まれているため、**常にTrueを返す**——これは、この関数のコメント自身が「将来Phase D以降」と明記していた通りの、既に用意されていた挙動である。つまり、`check_diff_safety()`が`passed`と判定した差分であっても、**Constitution上は常に人間の承認が必須**という前提が、既にコードとして保証されている。そのため、`passed`の差分は、`sigmaris_code_diff_proposals`へ`review_status="pending"`として保存するにとどめ、`requires_approval()`の呼び出し自体は、この前提を明示的に文書化する目的でのみ行った(判断根拠、レポートに明記)。

---

## 3. 「絶対にコミットしないこと」を、どう技術的に保証したか(要件1、最重要)

### 3.1 実装レベルでの保証(存在しないことによる保証)

新設した4ファイル(`code_diff_generation.py`・`code_diff_generation_runner.py`・`code_diff_proposal_store.py`・`scripts/run_code_diff_generation.py`)のいずれにも、**`subprocess`・`git`コマンド呼び出し・GitHub API呼び出しに相当するコードを、一切書いていない。** 各ファイルの役割は以下の通りに厳密に限定されている。

- `code_diff_generation.py`: LLM呼び出し(diff生成)+ 文字列の正規表現照合(安全性チェック)。ファイルシステムへの書き込み・ネットワーク上のgit操作は無い
- `code_diff_generation_runner.py`: 対象ファイルの**読み取り**(`Path.read_text()`、書き込みメソッドは一切呼ばない)+ Supabase REST経由のDB読み取り
- `code_diff_proposal_store.py`: Supabase REST経由のDB読み書きのみ
- `scripts/run_code_diff_generation.py`: 上記3つを呼び出すCLIのみ

### 3.2 実測による証明(依頼書が示唆した、E-1のハッシュ値パターンの応用)

`test_phase_f1_code_diff_generation.py::NeverCommitsProofTests`として、2種類の直接的な証明テストを実装した。

1. **静的な証明**: 上記4ファイルの実際のソースコードを読み込み、`import subprocess`・`subprocess.run(`・`import git`・`create_pull(`・`api.github.com/repos`等、git操作・コミット・PR作成の"実際の呼び出し"に相当するコードパターンが、1件も含まれていないことを確認する。**判断根拠(単語ではなくコードパターンで照合した理由)**: 初期実装では単純に`"subprocess"`という単語自体の不在を検証しようとしたが、これらのファイル自身のコメント(「`subprocess`・`git`コマンド呼び出しは一切存在しない」という説明文)にこの単語が含まれてしまい、テストが自己矛盾で失敗した。実際の呼び出しパターン(`subprocess.run(`等)にテスト対象を絞ることで、この問題を解消した——テスト作成中に発見した、意味のある教訓として記録する。
2. **動的な証明(E-1のSHA-256ハッシュ比較パターンの直接応用)**: パイプライン実行の前後で、以下3点を実測比較した。
   - `git rev-parse HEAD`(現在のコミットハッシュ)——変化なし=新しいコミットが一切発生していないことの直接証明
   - `git status --porcelain`(作業ツリーの状態)——変化なし=git上のステージング・変更状態に一切影響が無いことの証明
   - `backend/app/`配下の全`.py`ファイルのSHA-256ハッシュ——変化なし=対象ファイルの読み取りを行いながらも、書き込みは一切発生していないことの証明

   E-1が`backend/tests/`という限定的な範囲でこのパターンを確立していたのに対し、本タスクでは対象範囲を**`backend/app/`全体**(コード差分生成が理論上触れうる、実際のアプリケーションコードの全域)に拡張した——E-1よりも広い保証範囲が必要だと判断したため。

これら2つのテストは、実際に本パイプラインを(LLM呼び出しのみモックした状態で)フルに実行した上で検証しており、モックによる「呼ばれていないことの確認」だけでなく、**実際のgitリポジトリの状態を実測して**、変化が無いことを直接証明している。

---

## 4. 差分の保存・提示形式(要件5)

`sigmaris_code_diff_proposals`(新設、未適用)。E-4の`sigmaris_migration_review_queue`と全く同じ`review_status`ワークフロー(`pending`/`approved`/`rejected`、承認・却下は人間の明示的な呼び出しでのみ変わる)を踏襲した。

### 4.1 安全性チェック結果と`review_status`の対応

| `safety_check_status` | 意味 | `review_status` |
|---|---|---|
| `passed` | 安全性チェックを通過 | `"pending"`(人間の判断待ち) |
| `blocked_sensitive_file` | 機密ファイルに該当 | `"rejected"`(生成時点で自動的に、人間の判断を経ずに) |
| `blocked_safety_mechanism` | 安全機構ファイルに該当 | 同上 |
| `blocked_unexpected_target` | 意図しない対象ファイル | 同上 |
| `generation_failed` | LLM呼び出し失敗、または差分と認識できない出力、または対象ファイルが大きすぎる | 同上 |

**`blocked_*`/`generation_failed`のreview_statusを、生成時点で自動的に`"rejected"`にした判断根拠**: 依頼書「該当する場合、その差分は、生成されても、破棄され、記録にのみ残すこと(絶対に、次の工程に進めないこと)」に対応するため。これらの行は`get_pending_diff_proposals()`(review_status="pendingのみ返す)の対象から構造的に除外され、**人間のレビューキューには一切現れない**——記録として残りはするが、次の工程(人間による承認判断)へは進めない、という要件を、`review_status`という単一のフィールドで一貫して表現した。

### 4.2 保存される情報(人間がレビューしやすい形式)

`title`(仮説のタイトル)・`target_module`/`target_file`(対象)・`diff_text`(生成された差分そのもの)・`safety_check_status`/`safety_check_reason`(なぜこの判定になったか)・`hypothesis_id`/`hypothesis_priority_id`/`static_verification_id`(元になった仮説・D-3の優先順位付け結果・E-1の検証結果への、それぞれソフト参照)。E-4の`sigmaris_migration_review_queue`が確立した「D-3のphase_e_handoffとE-1の判定理由をそのまま引用する」という設計思想を、そのまま踏襲した。

実行方法: `python scripts/run_code_diff_generation.py [--limit N] [--dry-run]`。

---

## 5. テスト結果

`test_phase_f1_code_diff_generation.py`として31件のテストを作成した(scratchディレクトリ)。

```
TaskTypeTierTests (2件)
  PASS: CODE_DIFF_GENERATIONがadvanced tierへ正しくルーティングされること
  PASS: CODE_DIFF_GENERATIONがローカルLLM対象から除外されていること

GenerateDiffTests (4件)
  PASS: 正常な統一diff出力が正しく受理されること
  PASS: diff形式でない出力(拒否の自然文等)が破棄されること
  PASS: LLM呼び出し失敗時にNoneを返すこと(fail-open)
  PASS: 対象ファイルが大きすぎる場合、LLM呼び出し自体を行わずスキップ
        すること

ExtractDiffTargetPathsTests (3件)
  PASS: 単一の対象パスを抽出できること
  PASS: 複数の対象パスを抽出できること
  PASS: diffヘッダが無い場合は空集合を返すこと

CheckDiffSafetyTests (6件)
  PASS: 安全機構に触れない、明確なdiffが通過すること
  PASS: .envファイルへの変更が拒否されること
  PASS: config.pyへの変更が拒否されること
  PASS: 【重要】response_guard.pyへの変更が、安全機構ファイルとして
        拒否されること
  PASS: constitution_guard.py自体への変更が、安全機構ファイルとして
        拒否されること
  PASS: 【重要】生成された差分が、依頼した対象ファイル以外に触れて
        いる場合、拒否されること

ResolveModulePathTests (2件、モックなしの実ファイルシステムに対する
  直接検証)
  PASS: 実在するモジュール(response_guard)が正しく解決されること
  PASS: 存在しないモジュール名はNoneを返すこと

SelectCandidateHypothesesTests (4件)
  PASS: verdict="baseline_healthy_with_coverage"以外の仮説が対象外に
        なること
  PASS: 【重要】E-4のmigration_review_queueに既に登録されている仮説が、
        防御的に除外されること
  PASS: 対象ファイルが解決できない仮説が除外されること
  PASS: D-3のphase_e_handoffが見つからない仮説が除外されること

RunCodeDiffGenerationTests (4件)
  PASS: 安全性チェックを通過した差分がreview_status="pending"になること
  PASS: 【重要】安全機構ファイルに触れる差分が、生成時点で自動的に
        review_status="rejected"になること
  PASS: LLM生成失敗が、diff_text=""・review_status="rejected"として
        正しく記録されること
  PASS: 候補が0件の場合、空の結果を返すこと

CodeDiffProposalStoreTests (4件)
  PASS: 空リストの場合、HTTP通信すら発生させないこと
  PASS: 正しいペイロード形状でPOSTされること
  PASS: 【重要】record_review_decision()が"pending"を拒否すること
  PASS: get_pending_diff_proposals()が失敗時に空リストを返すこと

NeverCommitsProofTests (2件、依頼書の絶対原則の直接証明)
  PASS: 【最重要】生成4ファイルのソースコードに、git操作・コミット・
        PR作成に相当する実際の呼び出しパターンが、1件も含まれない
        ことの静的証明
  PASS: 【最重要】フルパイプラインの実行前後で、gitのHEAD・作業ツリー
        の状態・backend/app/配下の全ファイルのSHA-256ハッシュが、
        完全に一致することの実測による動的証明

31 passed
```

**テスト作成中に発見・修正した問題(2件、いずれも実バグではなくテスト自体の設計ミス)**:

1. `NeverCommitsProofTests`の初期実装が、禁止語彙として単なる`"subprocess"`という単語を検索していたため、この安全性自体を説明する自コメント(「`subprocess`は一切存在しない」)に反応して自己矛盾で失敗した。実際の呼び出しパターン(`subprocess.run(`等)への照合に修正した。
2. `code_diff_generation_runner.py`の初期実装は、対象ファイルパスを`backend/`相対(`app/services/xxx.py`)で計算していたが、これは`git diff`が実際に出力する形式・`rollback_runbook.md`が前提とするリポジトリルート相対の表記と一致しない、実際の不整合だった。リポジトリルート相対(`backend/app/services/xxx.py`)へ計算し直す形に修正した——これは人間が実際にこの差分を読む・将来適用する際に、パスの解釈が食い違うことを防ぐ、実質的な修正である。

既存の`backend/tests/`(16件)・F-1以前の全scratchテスト一式を含め、全て再実行しリグレッションが無いことを確認した。

```
31(本タスク) + 427(既存) = 458 passed, 7 subtests passed(合算実行)
```

**実モデルAPI・実データベースでの検証は行っていない。** テストは`get_llm_router()`・`supabase_rest`のHTTPクライアントをモックする形にとどまる(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。マイグレーション(`202607310058_code_diff_proposals.sql`)は作成のみ、適用は運用者側に委ねる。

---

## 6. 気づいた懸念点・次のステップ(F-2: E-1・E-2検証環境との統合)に向けた申し送り事項

1. **【最重要、1.1節で既述】「E-1・E-2両方を通過した仮説」という集合が、現在の設計上、存在しない。** E-1の`baseline_healthy_with_coverage`とE-2の`candidate_hypothesis_ids`(=`insufficient_signal`)は互いに素であり、F-1は`baseline_healthy_with_coverage`のみを採用した。F-2でこの2つの検証を統合する際、「E-1が高評価し、かつE-2でも実際に動作確認された仮説」という、依頼書が本来想定していたであろう集合をどう構成するかは、独立した設計課題として残っている——単純にはE-2自体を「個々の仮説を検証する」設計へ拡張する必要があり、これはE-2自身の報告書(`phase_e_report.md` 18章)が既に指摘していた懸念点(E-2が仮説の内容を一切読まない設計であること)と直結する。
2. **target_filesの代替としてmatched_modulesを採用した(1.2節)ことで、対象は「E-1のカバレッジ照合で偶然一致したモジュール」に限定される。** 現状`backend/tests/`が5モジュールしかカバーしていない(E-1報告書7章)ため、実際にF-1が生成を試みられる仮説の総数は、当面かなり少ないと見込まれる。D-2の生成プロンプトに対象ファイル名を出力させる拡張(D-2への変更を伴うため、本タスクの範囲外とした)を、F-2以降で検討する価値がある。
3. **`check_diff_safety()`のブロックリスト・安全機構ファイルリストは、いずれもファイルパスの文字列照合であり、意味解析を行わない。** 生成された差分の「内容」(実際にどんなコードが追加・削除されるか)そのものへの安全性チェックは、本タスクでは実装していない——依頼書が明示的に要求した2点(機密ファイル・Constitution Capability一線)のみに絞った、意図的なスコープ限定である。将来、差分の内容自体(例: 新しい外部HTTP呼び出しの追加、認証チェックの削除等)を検証する仕組みが必要になった場合は、別途の設計が必要になる。
4. **生成された差分の"正しさ"(実際にPythonとして構文的に妥当か、意図した変更を本当に達成しているか)は、一切検証していない。** D-2がSelf-Critique方式で仮説の質を検証したのと同種の、独立した批評ステップ(生成された差分を、別の視点で検証する)を追加するかどうかは、本タスクでは見送った——依頼書が「機械的に確認すること」と要求したのは機密ファイル・Constitution違反のみであり、意味的な正しさの検証は、承認前に人間が行うことを前提とした設計とした(判断根拠)。この点は、F-2または将来のタスクで、Self-Critiqueパターンの応用を検討する価値がある。
5. **`sigmaris_code_diff_proposals`に保存された、承認済み(`approved`)の差分を、実際にどう適用するか(ファイルへの書き込み・ブランチ作成・コミット・PR提出)は、依頼書の指示通り、本タスクでは一切設計していない。** これは正式にF-3のスコープとして申し送る——特に、承認された差分をどう安全に適用するか(例: E-2のサンドボックス環境で最終確認してから適用する等)は、F-2(E-1・E-2との統合)の結果を踏まえて設計されるべきだと考える。

---

## 7. マージについて(依頼書の指示により、本タスクは確認を待つ)

「テスト・検証」章の要件はすべて満たしていることを確認した(安全な仮説のみを対象にした生成・requires_special_review/マイグレーション仮説の除外・機密ファイル/Constitution該当差分の正しい破棄・「絶対にコミットしない」ことの静的+動的な実測証明・既存テストの回帰確認)。

**しかし、依頼書が明示的に指示した通り、本タスクはPhase D〜Fの中でも最も重要な絶対原則(コミットしない)を含むため、テストが全て通過した本時点でも、mainへは一切マージしていない。** ブランチ(`phase-f1-code-diff-generation`)を作業ツリーに残し、コミット・プッシュした上で、本報告を運用者へ提示し、確認を得てからマージする。
