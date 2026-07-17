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

**(2026-07-31 追記)運用者の確認を得て、本タスクはmainへマージ・プッシュ済み。**

---

# Phase F-2 実施報告: E-1・E-2検証環境との統合(仮説単位の検証の確立)

**(2026-07-17 追記)本タスクはmainへマージ・プッシュ済み。**

**作業ブランチ:** `phase-f2-e1-e2-integration`(mainから新規作成)
**範囲:** F-1で発見された「E-1とE-2、両方を通過した仮説」という集合が実際には存在しないという矛盾の解消。E-1(仮説単位の静的検証)・E-2(サンドボックス基盤全体の健全性証明)という、粒度の異なる2つの検証結果を、正直に区別した上で統合し、「仮説単位の検証結果」を、3段階の`verification_tier`として定義・実装した。F-1の検証対象をこの整理に基づいて調整した。**F-1の絶対原則(コミットしない)は、本タスクでも引き続き厳格に維持している(6章で実測により再証明)。**

---

## 8. 矛盾の正確な原因の整理(要件1・2)

### 8.1 E-1・E-2、それぞれの入力・出力の再整理

| | E-1(static_verification.py) | E-2(sandbox_verification.py) |
|---|---|---|
| **検証の単位** | **仮説単位**(1つの仮説につき1つの判定) | **セッション単位**(1回の起動につき1つの判定、仮説とは無関係) |
| **入力** | 1つの仮説の内容(`title`/`what_is_problem`等、`phase_e_handoff`経由)+ `backend/tests/`の既存カバレッジ | なし(仮説の内容を一切読まない、`sandbox_verification_runner.py`の設計、E-2報告書0章で既に明記済み) |
| **出力** | `excluded_migration`/`baseline_unhealthy`/`insufficient_signal`/`baseline_healthy_with_coverage`のいずれか(仮説ごとに1つ) | `failed_to_start`/`started_with_errors`/`started_but_checks_skipped`/`started_and_healthy`のいずれか(セッションごとに1つ) |
| **何を証明するか** | 「この仮説が触れると推定される領域に、既存テストがあるか」 | 「現在のコード(仮説の内容は適用しない)を、隔離環境で起動して、軽量ヘルスチェックが例外を出さないか」 |

### 8.2 「仮説単位の合否判定が、どこにも存在しない」ことの確認(要件1)

上記の再整理により、**F-1着手前の想定(「E-1とE-2、両方を通過した仮説」という集合が存在する)は、構造的に成立し得ない**ことを確認した。E-2は「どの仮説を検証したか」という情報を一切持たず、`sandbox_verification_runner.py::_get_candidate_hypothesis_ids()`が返す`candidate_hypothesis_ids`は、あくまで「E-1で`insufficient_signal`だった仮説のうち、人間が今後手動でテストする際の候補」という、参考情報の一覧にすぎない——**E-2自身がこれらの仮説を検証した、という意味は一切持たない。**

したがって、F-1着手時点では「仮説単位の検証結果」という概念そのものが、コードベースのどこにも定義されていなかった。本タスクは、この概念を新規に定義し、実装することが目的である。

---

## 9. 統合された検証フローの実装内容(要件2・3)

新設: `backend/app/services/hypothesis_verification.py`(純粋関数、I/Oなし)。`classify_verification_tier()`が、1件のE-1判定(仮説単位)と、直近1回分のE-2判定(セッション単位)から、以下の3段階に分類する。

| tier | 条件 | 意味 |
|---|---|---|
| `hypothesis_verified_coverage`(Tier 1) | E-1のverdict=`baseline_healthy_with_coverage` | 仮説の対象領域に、既存テストのカバレッジが実際に確認されている(**内容に基づく検証**) |
| `sandbox_infra_available_unverified_content`(Tier 2) | E-1のverdict=`insufficient_signal` **かつ** 直近のE-2実行のverdict=`started_and_healthy` | 仮説の対象領域に既存テストは無いが、サンドボックス基盤自体は直近で健全に起動・停止できている(**インフラの可用性のみの確認、内容は未検証**) |
| `not_eligible` | 上記いずれにも該当しない | 対象外 |

### 9.1 F-1の`code_diff_generation_runner.py::select_candidate_hypotheses()`の調整(要件3)

F-1時点ではTier 1のみを対象にしていたが、F-2でTier 2も候補に含めるよう拡張した。

**Tier 2の対象ファイル解決方法(重要な設計判断)**: Tier 2の仮説は、E-1の`matched_modules`が定義上常に空である(`insufficient_signal`は「既存テストとの一致が無い」ことそのものを意味するため)。そのため、Tier 1が使う「カバレッジ照合済みのモジュール名」を、Tier 2ではそのまま使えない。代わりに、`static_verification.py::extract_candidate_modules()`(E-1がカバレッジ照合の一次候補として内部で使っているのと同じ、仮説の自由文からモジュール名を推定する生の抽出関数)を、Tier 2の仮説の`phase_e_handoff`へ直接再適用し、`resolve_module_path()`で実在するファイルに解決できる最初の候補(決定的な選択のため、`set`をソートしてから走査)を採用した。

**判断根拠**: 新しい抽出ロジックを作らず、E-1が既に持っている関数をそのまま再利用した——このコードベース一貫の「既存資産の再利用」を、Tier 2という新しい経路でも徹底した。ただし、Tier 1の`matched_modules`(カバレッジと一致確認済み)より、Tier 2の抽出結果は明らかに確度が低い(単なるテキストからの推定であり、既存テストとの一致は保証されない)——この確度の違いは、`verification_tier`というフィールドで、生成された全ての差分提案に明示的に記録される(9.2節)。

### 9.2 生成された差分提案への、Tierの記録(要件2・4)

`sigmaris_code_diff_proposals`に、`verification_tier`・`verification_tier_reason`の2列を追加した(新規マイグレーション`202608010059_code_diff_proposals_verification_tier.sql`、ALTER TABLE、作成のみ・未適用)。**判断根拠(既存のF-1マイグレーションファイルを直接編集しなかった理由)**: このセッション一貫の方針として、一度コミットされたマイグレーションファイルは(たとえ本番未適用でも)編集せず、常に新しい追加マイグレーションを作る——E-4のロールバック調査(`rollback_runbook.md`)が確認した通り、このコードベースのマイグレーションは全て一方向(up only)設計であり、既存ファイルの遡及編集は、この既存の一貫性を崩すことになると判断した。

CLIの出力(`scripts/run_code_diff_generation.py`)にも、`verification_tier`を明示的に表示するラベルを追加した——**Tier 2の差分提案には、常に「内容は未検証」という注記が、人間のレビュー時に一目で分かる形で表示される。**

---

## 10. E-1・E-2、それぞれの役割の正確な区別(要件2・4、最重要)

**誤魔化さず、正確に記録する。**

- **E-1は、仮説の内容を検証する。** ある仮説が「触れると推定される領域」に、既存の回帰テストが実在するかどうかを、機械的に確認する。この検証は、仮説ごとに独立して行われ、結果も仮説ごとに記録される。
- **E-2は、仮説の内容を、一切検証しない。** E-2が検証するのは、「現在の(変更していない)Sigmarisのコードが、本番から隔離された環境で、安全に起動・停止でき、既存の軽量なヘルスチェックが致命的なエラーを起こさないか」という、**環境インフラそのものの健全性**である。E-2は仮説のテキストを一度も読まない(`sandbox_verification_runner.py`の設計そのもの)。
- **したがって、`sandbox_infra_available_unverified_content`(Tier 2)は、「この仮説は動作確認された」という意味では、決してない。** 正確には、「この仮説の対象領域には既存の安全網(テスト)が無いが、もし人間がこの仮説を今すぐ手動で検証したいと思った場合に使えるサンドボックス環境は、現在のところ壊れていない」という、**間接的で、限定的な**信頼性の表明にすぎない。

この区別を、`hypothesis_verification.py`のモジュールdocstring・`classify_verification_tier()`の各`reason`文字列・DBスキーマのコメント・CLI出力ラベルの、**4箇所全てに一貫して明記した。**

---

## 11. 将来、E-2が仮説単位の検証を行うための設計メモ(要件、実装はしない)

依頼書が例示した「仮説の内容を、一時的にコードに適用してから、サンドボックスを起動する」という方向性を、以下のように具体化して記録する。**本タスクでは一切実装しない。**

### 11.1 必要になる要素

1. **仮説の内容を、実際のコード差分として持つこと**: これは、まさにF-1(`code_diff_generation.py`)が既に実装している——F-1が生成する`diff_text`が、この将来の拡張の入力になりうる。
2. **その差分を、本番のgit状態に一切影響を与えずに、一時的な作業コピーへ適用すること**: これがF-1の絶対原則(「いかなる場合もコミットしない」)と、E-2の隔離要件(「本番環境に一切影響を与えない」)の両方を満たすための、最も難しい部分である。
3. **その一時的な作業コピーに対して、E-2のサンドボックス(別ポート・bench account・外部API無効化)を起動すること**: これはE-2が既に実装している起動・停止の仕組みを、通常のworking tree以外の場所に対しても使えるように、一般化するだけで済む可能性が高い。
4. **検証後、一時的な作業コピーを、痕跡なく破棄すること**。

### 11.2 具体的な実現方法の候補(このリポジトリに、既に前例がある)

**案A: `git worktree`の活用**。`docs/sigmaris/codebase_size_report.md`(6章)が、時系列調査のために`git worktree add --detach <tmp> <commit>`で過去のコミット時点のスナップショットを一時的な作業ツリーへ展開し、調査後に`git worktree remove`で破棄する、という手法を、**既にこのリポジトリで実際に使っている。** 同じ手法を応用し、`git worktree add --detach <tmp> HEAD`で現在のHEADから一時ツリーを作り、F-1が生成した(かつ人間が承認した)`diff_text`を、その一時ツリーの中だけに`git apply`で適用し、その一時ツリーのパスをカレントディレクトリとしてE-2のサンドボックスを起動する——**現在のブランチ・作業ツリー(git status)には、一切変更を加えない**(`git worktree`はメインの作業ツリーとは完全に独立したディレクトリを作る、gitの標準機能)。検証後は`git worktree remove --force <tmp>`で痕跡なく破棄する。

**案B: Phase E-3(Docker、現在見送り中)の再検討**。`docs/sigmaris/phase_e_report.md` 24.3節が既に整理した通り、E-3は「運用者がDocker可用性を確認する」等の条件が満たされるまで見送りとされている。しかし、コンテナのビルドプロセス自体に差分を適用する(`Dockerfile`のビルドステップ内で、承認された差分を一時的に当ててからイメージを作る)という設計は、ホストのgit状態に一切触れずに済む、**案Aよりもさらに強い分離**を提供できる。

### 11.3 推奨(判断根拠)

**案A(`git worktree`)を、将来の第一候補として推奨する。** 判断根拠: (1)既にこのリポジトリで実際に動作した前例がある、(2)Dockerのインストール可用性という、このセッションからは確認できない外部条件に依存しない、(3)E-2が既に実装した起動・停止ロジックを、対象ディレクトリを変えるだけで再利用できる可能性が高く、大規模な再設計が不要。ただし、`git worktree`を使う場合でも、**「どの承認済み差分を、どの一時ツリーに適用したか」を正確に記録する仕組み**(F-1・E-4が確立した`review_status`ワークフローの延長)と、**一時ツリーの確実な破棄を保証する仕組み**(E-2が確立した`terminate()`→`kill()`の二段階保証と同種の設計)の、両方が新たに必要になる——これ自体が、独立した1つのタスクに相当する規模だと考える。

---

## 12. F-1へのフィードバック内容(要件3)

9.1節で述べた通り、`code_diff_generation_runner.py::select_candidate_hypotheses()`を、Tier 1のみからTier 1+Tier 2へ拡張した。この変更は、**F-1が確立した安全性の仕組み(機密ファイル・安全機構ファイルのブロックリスト、意図しない対象ファイルの検出、`review_status`ワークフロー)には、一切手を加えていない**——変わったのは「どの仮説を候補にするか」という入力側のみであり、生成後の安全性チェック・保存・承認フローは、F-1のものをそのまま使う。

`code_diff_generation.py::generate_diff()`のプロンプト自体も変更していない——Tier 2の仮説に対しても、Tier 1と全く同じプロンプトで差分を生成する。**判断根拠(Tier別にプロンプトを変えなかった理由)**: 依頼書が要求したのは、あくまで対象範囲の調整であり、生成ロジック自体の変更ではない。Tierの違いは、生成後にどう扱われるか(`verification_tier`としてどう記録され、人間にどう提示されるか)で表現すれば十分であり、プロンプト自体を複雑化させる必要は無いと判断した——過度な複雑化を避ける、というこのコードベース一貫の方針を踏襲した。

---

## 13. テスト結果

`test_phase_f2_hypothesis_verification.py`として15件の新規テストを作成した(scratchディレクトリ)。加えて、F-1の既存テスト(`test_phase_f1_code_diff_generation.py`)のうち、`select_candidate_hypotheses()`を直接呼ぶ4件を、新しい依存(`get_recent_sandbox_verifications`)に合わせて更新した(振る舞いの変更ではなく、モックの追加のみ)。

```
ClassifyVerificationTierTests (7件)
  PASS: baseline_healthy_with_coverageがTier1になること
  PASS: Tier1はE-2の状態に関わらず成立すること(コンテンツベースの検証は
        インフラの状態と無関係であることの直接検証)
  PASS: 【重要】insufficient_signal + E-2健全 でTier2になり、reasonに
        「内容」という語(未検証であることの明記)が含まれること
  PASS: insufficient_signal + E-2実行なし でnot_eligibleになること
  PASS: insufficient_signal + E-2不健全 でnot_eligibleになること
  PASS: insufficient_signal + E-2起動失敗 でnot_eligibleになること
  PASS: excluded_migration・baseline_unhealthyは、いずれもnot_eligible
        になること

WidenedCandidateSelectionTests (4件)
  PASS: 【重要】Tier2の仮説が、直近E-2が健全な場合に候補へ含まれること
  PASS: Tier2の仮説が、直近E-2が不健全な場合に除外されること
  PASS: Tier2の仮説で、対象ファイルが解決できない場合に除外されること
  PASS: 【重要】Tier1・Tier2が同時に候補になり、それぞれ正しいtierが
        付与されること

VerificationTierPropagationTests (1件)
  PASS: verification_tier/reasonが、候補選定から最終的な提案結果まで
        正しく引き継がれること

NeverCommitsProofStillHoldsTests (2件、依頼書「絶対原則の維持」への
  直接対応)
  PASS: 【最重要】F-2で変更・新設した4ファイルにも、git操作・コミット・
        PR作成に相当する呼び出しパターンが、1件も含まれないこと
  PASS: 【最重要】F-2の変更後も、フルパイプライン実行前後でgit HEAD・
        作業ツリー状態・backend/app/配下全ファイルのSHA-256ハッシュが
        完全一致すること(F-1の実測証明の再検証)

15 passed
```

既存の`backend/tests/`(16件)・F-1以前の全scratchテスト一式(F-1の更新済み4件を含む)を、全て再実行しリグレッションが無いことを確認した。

```
15(本タスク) + 458(既存、F-1の4件更新後) = 473 passed, 7 subtests passed(合算実行)
```

**実モデルAPI・実データベースでの検証は行っていない。** テストは`supabase_rest`のHTTPクライアントをモックする形にとどまる(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。マイグレーション(`202608010059_code_diff_proposals_verification_tier.sql`)は作成のみ、適用は運用者側に委ねる。

---

## 14. 気づいた懸念点・次のステップ(F-3: Constitution連携、承認フロー、プルリクエスト作成)に向けた申し送り事項

1. **Tier 2の対象ファイル解決(`extract_candidate_modules()`の生の再利用)は、Tier 1より明らかに確度が低い、テキストからの推定にとどまる。** 実際にTier 2経由で生成される差分提案が、どの程度「見当違いのファイルへの変更」になるかは、実データでの検証ができていない(この環境の制約)。運用者が実際に`scripts/run_code_diff_generation.py`を実行し、Tier 2の提案の質を確認することを推奨する。
2. **「直近のE-2実行が健全かどうか」の判定に、鮮度(実行からの経過時間)を考慮していない(9章、`classify_verification_tier()`のdocstring内の判断根拠)。** 数週間前の健全なE-2実行結果が、現在のサンドボックス基盤の状態を正しく反映しているとは限らない。過度な複雑化を避けるため、本タスクでは鮮度判定を追加しなかったが、実運用でこれが問題になった場合は、`classify_verification_tier()`に鮮度の閾値を追加することを検討する余地がある。
3. **11章の設計メモ(仮説単位の実際の動作確認)は、F-1の差分生成とE-2のサンドボックス起動を、`git worktree`で安全に橋渡しする、という具体的な方向性を示したが、実装は一切行っていない。** これが実装されれば、F-1の絶対原則(コミットしない)と、より踏み込んだ動作確認の両立が可能になると考えられるが、「一時ツリーの確実な破棄」という、E-2の`terminate()`→`kill()`と同種の、新しい安全保証の設計が必要になる——独立したタスクとして着手する価値がある。
4. **F-3(Constitution連携、承認フロー、プルリクエスト作成)に向けて**: F-1・F-2を通じて、`sigmaris_code_diff_proposals`には、`review_status="pending"`の(Tier 1・Tier 2いずれかでラベル付けされた)提案が蓄積される状態になった。F-3は、この`review_status`を`"approved"`に変える、実際の人間の判断フロー(誰が、どうやって承認するか)と、承認された差分を、**依然としてF-1の絶対原則を守りながら**(=人間が最終確認するまでは、いかなる自動適用も行わない)、実際にコードへ反映する仕組み(ブランチ作成・コミット・PR提出)を設計することになる。11章の設計メモ(`git worktree`)が、F-3の「承認された差分を、まず隔離環境で最終確認してから適用する」というステップに、直接接続できる可能性がある。

---

## 15. マージについて

「テスト・検証」章の要件をすべて満たしていることを確認した(統合された検証フローの意図通りの動作・F-1の検証対象の正しい調整・既存テストの回帰確認)。既存機能(F-1・D・E全体・Phase R・Phase G・Phase S・B群全体)への悪影響も、全テスト再実行によって確認した。**F-1で確立された「絶対にコミットしない」という原則は、本タスクでも実測により再証明した(13章)。** 依頼書の指示通り、確認を待たずmainへマージ・プッシュする。

---

# Phase F-3 実施報告: 承認フロー、及び、承認後のプルリクエスト作成(Phase D〜Fの、最終ステップ)

**作業ブランチ:** `phase-f3-approval-and-pr-creation`(mainから新規作成)
**範囲:** F-1が生成し、F-2がTierで区別した「承認待ち」のコード差分提案を、海星さんが確認・承認・却下できる仕組みと、**承認された場合のみ**、実際にGitHub上へブランチ作成・コミット・プルリクエスト提出まで実行する仕組みを実装した。Phase D(根拠収集)〜Phase F(コード差分生成)まで積み上げてきた、Sigmarisの自己改善パイプラインの、最後の輪を閉じるタスクである。**mainブランチへの直接の影響は、本タスクの実装のどこにも存在しない**——実際に作成されるのは、GitHub上の新規ブランチとプルリクエストのみであり、mainへのマージは、依然として海星さん自身が、通常のGitHub操作で行う。依頼書の指示通り、テストが全て通過した現時点でも、mainへは一切マージせず、本報告を提示した上で運用者の確認を待つ。

---

## 16. 前提として確認したこと

- `docs/sigmaris/phase_f_report.md`(F-1・F-2、1〜15章): F-1の絶対原則(「いかなる場合も自動的にコミット・PR化しない」)と、その静的・動的の両面での実測証明パターン、F-2の`verification_tier`によるTier区別、14章の申し送り事項(F-3への引き継ぎ)
- `docs/sigmaris/constitution.md` Article 6、および`constitution_guard.py`: `CAPABILITY_APPROVAL_REQUIRED_CATEGORIES`に`"code_change"`が含まれ、`requires_approval("code_change")`が常にTrueを返すこと(コメント「将来Phase D以降」が、まさに本タスクを指していたことを確認した)
- `docs/sigmaris/phase_e_report.md`・`rollback_runbook.md`: E-4が確立した`review_status`(`pending`/`approved`/`rejected`)ワークフローのパターン、ロールバックが`git revert -m 1`で機能する前提(=本タスクが生成するPRも、通常のGit運用に乗ることの確認)
- **削除済み`self_improvement.py`のGitHub連携実装**(git履歴 `bea3ada~1:backend/app/services/self_improvement.py`から参照): `_create_github_pr()`が、(1) デフォルトブランチとその先端SHAの取得、(2) 当日のPR作成数の上限チェック(ブランチ名の接頭辞でカウント)、(3) 新規ブランチ作成、(4) 対象ファイルの現在の内容とSHAの取得、(5) 内容の更新とコミット、(6) プルリクエスト作成、という順序で、`httpx.AsyncClient`のみを使い、**ローカルのgitには一切触れず、全てGitHub REST APIへのHTTPリクエストとして実装していた**ことを確認した——この「ローカルgitに触れない」という設計自体は、本タスクでも踏襲する価値があると判断した(17章で詳述)。一方で、旧実装には**重大な限界**があった:統一diffを実際には適用しておらず、`proposal.proposed_change`のテキストを、対象ファイルの末尾にHTMLコメント付きで追記するだけだった(=「diffの適用」ではなく「テキストの追記」)。本タスクは、この限界を解消し、F-1が実際に生成する統一diff形式を、正しく適用する必要がある。

---

## 17. 承認待ちの提示形式(要件1)

新設CLI `backend/scripts/review_diff_proposals.py`(4つのサブコマンドのみ):

| サブコマンド | 動作 | GitHub/DBへの書き込み |
|---|---|---|
| `list` | `review_status="pending"`の提案を一覧表示(タイトル・対象ファイル・検証Tier・作成日時) | なし(読み取りのみ) |
| `show <id>` | 1件の詳細(差分本文全文・検証Tierとその理由・F-1安全性チェック結果・**Constitution注記**)を表示 | なし(読み取りのみ) |
| `approve <id> [--notes] [--reviewed-by]` | **海星さんが、明示的にこのコマンドを実行した場合のみ**、承認を記録し、GitHub PR作成まで実行する | **唯一、書き込みが発生しうる経路** |
| `reject <id> [--notes] [--reviewed-by]` | 却下を記録するのみ | DB書き込みのみ(GitHubには一切アクセスしない) |

**判断根拠(専用APIエンドポイントではなくCLIを選んだ理由)**: 依頼書は「専用のAPIエンドポイント、あるいは、CLIで、明確なコマンドを実行する等」の両方を選択肢として例示していた。既存のE-4(`migration_review_queue`)・D-2/D-3(`requires_special_review`)のいずれも、レビュー内容の提示・記録はCLIスクリプト経由で運用されており(専用FastAPIエンドポイントは無い)、本タスクもこの既存の運用パターンを踏襲した。新しいHTTPエンドポイントを追加すると、認証・認可(「誰が承認操作を叩けるか」)という、本タスクのスコープを超える新しい検討課題が発生する——CLIであれば、「このマシン上のターミナルから、海星さん自身が明示的にコマンドを打つ」という、既存の運用実態にそのまま一致する(判断根拠)。

`show <id>`は、依頼書の要求(「Constitution(S-4)に照らして、注意すべき点があれば、それも、明記すること」)に対応し、`requires_approval('code_change')`の実際の戻り値を、レビュー画面に毎回明示的に出力する(18章で詳述)。

---

## 18. 承認・却下の記録方法(要件2・5)

E-4(`migration_review_queue_store.py`)・F-1(`code_diff_proposal_store.py`)と、全く同じ`pending → 人間が明示的に決定する`パターンを踏襲した。

- `record_review_decision(proposal_id, *, status, notes, reviewed_by)`(F-1で既存、変更なし): `status`は`"approved"`/`"rejected"`のみを受け付け、`"pending"`への差し戻しはValueErrorで拒否する(F-1・E-4と同一の制約)。
- **新規**: `get_diff_proposal_by_id(proposal_id)` — 承認・却下の判断、およびPR作成の実処理のために、1件の提案を、`diff_text`本文込みで取得する。見つからない場合はNone(呼び出し元は、これを「承認不可」として扱う、fail-closed)。
- **新規**: `record_pr_outcome(proposal_id, *, status, pr_url, branch, error)` — 承認後の実行結果を記録する。**`review_status`(人間が承認したかどうか)とは、意図的に別カラム(`pr_creation_status`)に記録する**——「人間はXを承認した」という事実と、「システムが実際にGitHubへ到達できたか」という事実を、絶対に混同しないための設計判断(19章の段階Bのケースで、この分離が本質的に重要になる)。

新規マイグレーション`202608020060_code_diff_proposals_pr_outcome.sql`(ALTER TABLE、作成のみ・未適用、既存マイグレーションファイルは編集しない、F-2までと同じ一貫方針)で、`sigmaris_code_diff_proposals`に`pr_creation_status`・`pr_url`・`pr_branch`・`pr_creation_error`の4列を追加した。

却下(`reject_diff_proposal()`)は、`record_review_decision(status="rejected", notes=...)`を呼ぶのみで完結し、**GitHub関連のコードには一切到達しない**(`diff_approval.py`のモジュールdocstring、および21章の証明テスト参照)——依頼書の要件5(「却下の場合、理由が、正しく、記録されること」)は、`notes`引数として、そのまま`review_notes`列へ記録される。

---

## 19. 承認後の実行内容(ブランチ・コミット・PR作成の、具体的な実装)(要件3)

### 19.1 全体構成(新設ファイル)

- `backend/app/services/diff_patch.py`(純粋関数、I/Oなし): 統一diffのテキストを、対象ファイルの実際の内容に適用する、独自実装のパッチ適用ロジック。
- `backend/app/services/github_pr_publisher.py`: **このコードベース全体で唯一、GitHubへの書き込みAPI呼び出し(ブランチ作成・コミット・PR作成)を行うモジュール。**
- `backend/app/services/diff_approval.py`: 承認・却下のオーケストレーション。`approve_diff_proposal()`が、承認確定後に`github_pr_publisher.publish_approved_diff()`を呼び出す、**唯一の経路。**
- `backend/scripts/review_diff_proposals.py`: 人間が直接叩く、唯一の入口(17章)。

### 19.2 `diff_patch.py`: なぜ独自実装が必要だったか

`backend/pyproject.toml`の依存関係を確認したが、diff適用ライブラリ(`unidiff`・`patch`等)は存在しない。加えて、16章で確認した通り、旧`self_improvement.py`も、実際にはdiffを適用していなかった(テキストの追記のみ)——参考にできる既存実装が、このリポジトリのどこにも無かった。

`apply_unified_diff(original_content, diff_text)`は、`@@ -a,b +c,d @@`形式のハンクヘッダーを正規表現で解析し、コンテキスト行(` `)・削除行(`-`)・追加行(`+`)を、元のファイル内容と1行ずつ照合しながら、パッチ後の内容を再構成する。複数ハンクに対応する。

**fail-closed設計(判断根拠)**: コンテキスト行・削除行が、実際のファイル内容と一致しない場合(F-1の差分生成時点から、対象ファイルの内容が変化している可能性がある)、`DiffApplyError`を送出して処理を中断する。silent(不一致を無視して、不正確な結果を黙って返す)にしなかった理由は、中途半端に破損したファイル内容が、実際にGitHub上へコミットされる事態を、絶対に避けるためである——この判断は、F-1の「対象ファイルが大きすぎる場合は、無理に生成させず明示的にスキップする」(`MAX_FILE_CHARS_FOR_DIFF`)という、同じ「無理をしない」設計方針の延長線上にある。

### 19.3 `github_pr_publisher.py`: 旧`self_improvement.py`との異同

**踏襲した点**: HTTPのみ(`httpx.AsyncClient`)でGitHub REST APIを呼び、**ローカルのgitコマンドには一切触れない**という設計。デフォルトブランチ・先端SHAの取得 → 当日のPR作成数上限チェック(`_MAX_DAILY_PRS = 3`、旧実装の値をそのまま踏襲——新しい数値を独断で選ばなかった)→ 新規ブランチ作成 → 対象ファイルの現在の内容・SHA取得 → 内容更新・コミット → PR作成、という処理順序も、旧実装と同一である。

**変更した点(判断根拠、それぞれ明記)**:
1. **diffの実適用**: `apply_unified_diff()`で、実際の統一diffを、GitHub上の対象ファイルの**今この瞬間の内容**(承認時点の内容ではなく、PR作成直前に改めて取得した内容)に対して適用する。承認から実行までの間に、対象ファイルがmain上で変化していた場合、`DiffApplyError`が送出され、`pr_creation_status="failed"`として記録される(黙って古い内容に基づくコミットを作らない)。
2. **専用の書き込みクレデンシャル**: `settings.sigmaris_pr_github_token`/`sigmaris_pr_github_repo`を新設した(`config.py`)。既存の`github_token`は、`research_agent.py`のGitHubトレンド検索(読み取り専用、レート制限ヘッダーの確認のみ)で使われている——**書き込み権限を持つクレデンシャルと、読み取り専用のそれを、運用者がenv上で混同しないようにするため**、意図的に別の変数名にした(独断の判断根拠)。
3. **新しいブランチ命名規則**: `sigmaris/self-improve-*`(削除済み旧実装)から`sigmaris/f3-approved-*`へ変更した。**判断根拠**: 削除済みの、Constitutionと連携していなかった旧仕組みの成果物と、本タスクで新設した、正式な承認フローを経た成果物とを、運用者がGitHub上のブランチ一覧を見た瞬間に区別できるようにするため。
4. **3段階目の防御的安全性チェック**: `publish_approved_diff()`内で、実際のGitHub書き込みの直前に、`check_diff_safety()`をもう一度呼ぶ(20章「多層防御」参照)。

### 19.4 mainブランチへの非影響(要件3)

`github_pr_publisher.py`が呼び出すGitHub APIは、`repos/{repo}/git/refs`(新規ブランチ作成、`base=default_branchの先端SHA`)・`repos/{repo}/contents/{path}`(その新規ブランチに対してのみコミット)・`repos/{repo}/pulls`(head=新規ブランチ、base=default_branch)の3種類のみであり、**default_branch(通常main)へ直接push・直接コミットするAPI呼び出しは、いずれのコードパスにも存在しない。** mainへの反映は、作成されたプルリクエストを、海星さんが通常のGitHub操作(レビュー・マージボタン)で行うことを前提とした設計であり、これは21章の証明テストで、ローカルgit状態の非変化という形でも間接的に裏付けられている(実際のコミットは、常にGitHubサーバー上の新規ブランチに対してのみ発生し、このマシンのローカルなmainブランチには、そもそも一度も触れない)。

---

## 20. Constitutionとの最終連携の内容(要件4)

`diff_approval.py::verify_constitution_and_safety_gate()`が、承認フローの中で**2回**(段階A・段階B)呼び出される、共通ゲート関数である。

1. **ドキュメント的確認**: `constitution_guard.requires_approval("code_change")`を呼び出し、Trueであることを確認する。S-4の4カテゴリ定義は固定文書ベースであり、動的な判定ロジックではない——このタスク自体が「なぜ存在するか」の根拠を、実行時にも毎回明示的に再確認する、という位置づけである(万が一、将来`constitution_guard.py`の定義が変わり、`"code_change"`が承認不要になった場合、これを検知して処理を止める安全弁でもある)。
2. **機械的な実質チェック**: F-1の`check_diff_safety()`(機密ファイル・安全機構ファイル・意図しない対象ファイルの検出)を、そのまま再利用する。

**2段階での呼び出しタイミング(依頼書「承認・実行の、各段階で」への対応)**:

| 段階 | タイミング | 失敗した場合 |
|---|---|---|
| 段階A | `record_review_decision(status="approved")`を呼ぶ**直前** | 承認そのものを記録しない(`rejected_at_gate`) |
| 段階B | `github_pr_publisher.publish_approved_diff()`を呼ぶ**直前**(承認は既に記録済み) | 承認の記録は**取り消さない**が、実行を中断し、`pr_creation_status="blocked_by_constitution_recheck"`として記録する |

**段階Bが独立して必要な理由(依頼書「もし、承認された差分が、何らかの理由で、Constitutionのチェックに、後から、抵触することが、判明した場合、実行を、中断し、報告すること」への直接対応)**: 承認から実行までの間に、diffの内容自体は変わらなくても、判定ロジック側の状態(例: ある種の一時的な障害、または将来の拡張で判定条件が動的になった場合)が変わりうる、という仮説的なシナリオに備えた、二重の安全網である。**段階Bで失敗しても、承認の記録(`review_status="approved"`)自体は取り消さない**——「人間はXを承認した」という事実と、「システムは、その後の再チェックで、実行を拒否した」という事実の、両方が、正直な監査証跡として、別々のカラム(`review_status`と`pr_creation_status`)に残る設計にした(18章)。承認記録を取り消して`pending`に戻すことも検討したが、それは「人間の判断そのものを、システムが後から書き換える」ことになり、E-4・F-1が確立した「pendingへの差し戻しを拒否する」という既存の制約にも反するため、採用しなかった(判断根拠)。

さらに、19.3節で述べた通り、`github_pr_publisher.py`自身も、実際のGitHub書き込みの直前に**3回目**の`check_diff_safety()`呼び出しを行う——`diff_approval.py`を経由しない、想定外の呼び出し元が万一将来追加された場合にも、このモジュール単体で安全性を担保できるようにするための、多層防御である(判断根拠: 「唯一の書き込みモジュール」自身が、自らの安全性を、呼び出し元に依存せず証明できる状態にしておくべきと判断した)。

---

## 21. 「未承認は、絶対に実行されない」ことの、証明テストの内容(要件1・2、最重要)

F-1・F-2が確立した「静的+動的の両面から、実測で直接証明する」パターンを、そのまま踏襲した。

### 21.1 静的証明

1. **ローカルgit操作の不在**: `diff_patch.py`・`github_pr_publisher.py`・`diff_approval.py`・`code_diff_proposal_store.py`・`review_diff_proposals.py`のソーステキストに、`import subprocess`・`subprocess.run(`・`import git`・`git.Repo(`等の、ローカルgit操作に相当するコードパターンが、1件も含まれないことを確認する(F-1と同じ「単語一致ではなく、実使用パターン一致」の教訓を踏襲——後述21.3節)。
2. **importグラフレベルの証明(本タスクで新規に追加した観点)**: `github_pr_publisher.publish_approved_diff`への、実際のimport・呼び出しパターン(`from app.services.github_pr_publisher`等)が、`diff_approval.py`以外の、`backend/app/`配下のいかなるファイル(既存の全Runner・スケジューラを含む)にも存在しないことを、`app/`ディレクトリ全体をgrepして確認する。同様に、`backend/scripts/`配下でも、`review_diff_proposals.py`以外のいかなるスクリプトにも、`approve_diff_proposal(`の呼び出しが存在しないことを確認する——**「承認の実行に到達できる経路が、CLI上のこの1コマンドしか無い」ことの、コードベース全体を対象にした機械的な証明。**
3. **`reject_diff_proposal()`関数本体の直接検査**: 関数のソーステキストそのものを切り出し、`publish_approved_diff`という文字列が、その本体内に一切現れないことを確認する。

### 21.2 動的証明

1. **一覧表示・却下操作**を実行した前後で、ローカルgitのHEAD・`git status --porcelain`・`backend/app/`配下全ファイルのSHA-256ハッシュが、完全に一致することを実測する。
2. **【最重要】承認され、GitHub呼び出し(モック済み)まで到達する、フルフローを実行した場合でも**、同様にローカルgit状態が一切変化しないことを実測する。これは、F-1/F-2の「コミットが一切発生しない」証明とは異なり、**「実際にGitHubへの書き込みが発生する経路を、承認によって実際に通過させた上で」、それでもローカルには一切影響が無いことを証明する**、という点で、F-1/F-2より一段階踏み込んだ証明になっている——本タスクのアーキテクチャ上の性質(19.4節: 実際のコミットは、常にGitHubサーバー上の新規ブランチに対してのみ発生し、ローカルのワーキングツリー・mainブランチには、指一本触れない)を、実測で裏付けるものである。
3. **ゲートの実効性の証明**: 承認前(段階A)で安全性チェックに失敗するケースでは、`record_review_decision`(承認の記録自体)が呼ばれないこと、承認後(段階B)で失敗するケースでは、承認は記録されるが`publish_approved_diff`が一切呼ばれないことを、それぞれモックの呼び出し回数(`assert_not_called()`/`assert_awaited_once()`)で直接検証する。

### 21.3 静的証明の調整(F-1の教訓の踏襲)

当初、`github_pr_publisher`という単語そのものへの単純な文字列一致でimportグラフを検査したところ、`config.py`・`code_diff_proposal_store.py`・`diff_patch.py`の**説明コメント中**(「github_pr_publisher.py以外のいかなるモジュールからも参照されない」等、本モジュールの制約を説明する文章)に、この単語が登場していたため、誤検知した。F-1の`NeverCommitsProofTests`が、かつて`"subprocess"`という単語そのものへの一致で、同様の誤検知(自身の説明コメント中の単語に反応)を起こし、実際の使用パターン(`"import subprocess"`等)への一致に切り替えて解消した、という前例と、**全く同じクラスの調整**だと判断し、`from app.services.github_pr_publisher`・`github_pr_publisher.publish_approved_diff(`等、実際のimport・呼び出しパターンのみに対象を絞ることで解消した。

---

## 22. テスト結果

`test_phase_f3_approval_and_pr.py`として32件の新規テストを作成した(scratchディレクトリ)。

```
ApplyUnifiedDiffTests (7件)
  PASS: 単一ハンクが正しく適用されること
  PASS: 複数ハンクが順序通りに適用されること
  PASS: 【重要】コンテキスト行が対象ファイルの実際の内容と一致しない場合、
        DiffApplyErrorでfail-closedすること
  PASS: 削除行が一致しない場合も同様にfail-closedすること
  PASS: 追加のみのハンク(ファイル末尾への追記)が正しく処理されること
  PASS: ハンクが1つも無いdiff_textはDiffApplyError
  PASS: 末尾に改行の無いファイルへの適用で、余計な改行を付与しないこと

PublishApprovedDiffTests (5件)
  PASS: 認証情報未設定時、HTTP呼び出しを一切発生させずskipped_not_configured
        を返すこと
  PASS: パストラバーサルを含む対象ファイルを、HTTP呼び出し前にblockすること
  PASS: 機密ファイル(.env)への差分を、HTTP呼び出し前の3回目の安全性
        チェックでblockすること(19.3節の多層防御)
  PASS: 【重要】正常系: モック済みGitHub APIに対し、正しい順序(デフォルト
        ブランチ取得→上限確認→ブランチ作成→ファイル取得→diff適用→
        コミット→PR作成)でリクエストが送られ、PUTのペイロードに実際に
        diffが適用された内容が入っていること
  PASS: 当日のPR作成上限に達している場合、ブランチ作成より前にskipされること

VerifyConstitutionAndSafetyGateTests (3件)
  PASS: 安全な差分がゲートを通過すること
  PASS: 機密ファイルへの差分がゲートで拒否されること
  PASS: 【重要】requires_approval('code_change')が常にTrueであること
        (Constitutionが、本タスク全体の存在根拠であることの直接確認)

ApproveDiffProposalTests (6件)
  PASS: 正常系: 承認記録→publish呼び出し→PR URL取得の順で完結すること
  PASS: pending以外の状態にある提案は、publishを呼ばずに拒否されること
  PASS: 存在しない提案IDは、publishを呼ばずに拒否されること
  PASS: F-1安全性チェックがpassed以外の提案は、承認自体を拒否すること
  PASS: 段階A(承認記録直前)のゲート失敗時、承認そのものが記録されない
        ことの直接確認(record_review_decisionが呼ばれない)
  PASS: 【最重要】段階B(承認記録後・実行直前)のゲート失敗時、承認の
        記録は行われるが、publish_approved_diffは一切呼ばれず、
        pr_creation_status="blocked_by_constitution_recheck"として
        記録されることの直接確認(依頼書「方針4」への対応の実測証明)

RejectDiffProposalTests (3件)
  PASS: 却下時、理由(notes)が正しく記録されること
  PASS: 存在しない提案IDの却下は失敗すること
  PASS: 既にレビュー済みの提案の却下は失敗すること

StoreAdditionsTests (3件)
  PASS: get_diff_proposal_by_idが該当行を返すこと/該当無しでNoneを返すこと
  PASS: record_pr_outcomeが正しいペイロード形状で送信されること

NeverExecutesWithoutApprovalProofTests (5件、依頼書の最重要要件への直接対応)
  PASS: 【最重要】新規5ファイルに、ローカルgit操作に相当するコード
        パターンが1件も含まれないこと
  PASS: 【最重要】github_pr_publisherへの実際のimport・呼び出しが、
        diff_approval.py以外のいかなるapp/配下ファイル・review_diff_
        proposals.py以外のいかなるscripts/配下ファイルにも存在しない
        こと(importグラフレベルの証明)
  PASS: reject_diff_proposal()の関数本体に、publish_approved_diffへの
        参照が一切無いこと
  PASS: 一覧表示・却下操作の前後で、ローカルgit状態(HEAD・working tree・
        backend/app/全ファイルのSHA-256)が完全一致すること
  PASS: 【最重要】承認され、(モック済みの)GitHub呼び出しまで到達する
        フルフローを実行しても、ローカルgit状態が完全一致すること

32 passed
```

既存の`backend/tests/`・F-1/F-2以前の全scratchテスト一式を含めて再実行し、リグレッションが無いことを確認した。

```
32(本タスク) + 473(既存、F-2まで) = 505 passed, 7 subtests passed(合算実行)
```

**実際のGitHub APIへの書き込みは、一切行っていない**——`PublishApprovedDiffTests`は、`httpx.AsyncClient`をモックし、依頼書の指示通り「実際のGitHubへの、書き込みに繋がる」部分を、テスト環境で安全にシミュレーションした。実モデルAPI・実データベースでの検証も行っていない(依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない)。マイグレーション(`202608020060_code_diff_proposals_pr_outcome.sql`)は作成のみ、適用は運用者側に委ねる。`SIGMARIS_PR_GITHUB_TOKEN`/`SIGMARIS_PR_GITHUB_REPO`は、本セッションでは値を設定していない(=`approve`コマンドを実行しても、`skipped_not_configured`として、実際のPR作成は発生しない状態のまま)。

---

## 23. Phase D〜F、全体を通じての振り返り・残っている懸念事項の総まとめ

### 23.1 何が完成したか

Phase D(根拠収集→仮説生成→優先順位付け・検証可能性)→ Phase E(サンドボックス検証環境: 静的検証・動的サンドボックス起動・マイグレーションレビュー・ロールバック手順)→ Phase F(コード差分生成→E-1/E-2統合→承認フロー→PR作成)という、一連の「自己改善エンジン」が、**Sigmarisの行動ログ・仮説を、人間の承認を経た、実際のGitHubプルリクエストへ変換する**ところまで、一貫して繋がった。各段階の境界は、以下の通り明確に分離されている:

- **D-1〜D-3**: 「何を改善すべきか」の言語化(LLM生成、根拠に基づく仮説、優先順位付け)
- **E-1〜E-4**: 「その言語化された改善が、安全に検証できる状態にあるか」の機械的確認(既存テストカバレッジ、隔離環境での起動確認、マイグレーションのレビュー待ち化)
- **F-1〜F-2**: 「その改善を、実際のコード差分として具体化する」段階(LLM生成、機密ファイル・安全機構ファイルの機械的ブロック、検証Tierの正直な区別)
- **F-3**: 「人間が最終確認し、実際にGitHub上のPRとして提出する」段階

### 23.2 一貫して守られた設計原則

1. **各段階で、独立した機械的な安全網を持たせる**(E-1のカバレッジ照合、F-1の安全性チェック、F-3の3段階ゲート)——1つのチェックに全てを委ねない、多層防御。
2. **「できていないこと」を、正確に記録する**(F-2のTier区別、E-2が仮説の内容を検証しないことの明記、F-3の`pr_creation_status`と`review_status`の分離)——過大な主張を避け、監査証跡として正直であることを優先した。
3. **人間の判断が必要な箇所には、必ず`pending`状態を経由させ、自動化された経路を作らない**(E-4・F-1・F-3、いずれも同じ`review_status`パターン)。
4. **絶対原則(コミットしない)は、実測(静的+動的)で毎回再証明する**——口頭やコメントでの説明だけに頼らず、テストコードとして機械的に保証し続けた(F-1で確立、F-2・F-3で再証明)。
5. **既存資産の再利用を徹底し、新しい重量級の仕組みを作らない**(F-1のブロックリストをF-3でも再利用、E-4のワークフローパターンをF-1・F-3でも再利用、旧`self_improvement.py`のGitHub呼び出し順序をF-3でも参考にした)。

### 23.3 残っている懸念事項(未実装・未検証のまま申し送るもの)

1. **【最重要、実運用で最初に確認すべきこと】実際のGitHub APIキー・リポジトリでの動作は、一度も検証されていない。** `SIGMARIS_PR_GITHUB_TOKEN`/`SIGMARIS_PR_GITHUB_REPO`を設定し、実際に`approve`コマンドを実行して、GitHub上に実際のブランチ・PRが作成されることを、運用者が最初に確認することを強く推奨する——モックでのテストは、リクエストの形状・順序・多層防御の発動条件までは検証したが、GitHub側の実際のAPI仕様の細部(レート制限、権限スコープの過不足、対象リポジトリのブランチ保護ルール等)までは検証できていない。
2. **F-2の11章で示した`git worktree`による、仮説単位の実動作確認(承認前に、隔離環境で実際に動かしてみる)は、依然として未実装のまま。** F-3は、あくまで「人間が差分を読んで判断する」ことを前提とした設計であり、承認前にサンドボックスで自動実行してみる、という、より踏み込んだ検証は、独立したタスクとして残っている。
3. **F-2で申し送られた、Tier 2(`sandbox_infra_available_unverified_content`)経由の差分提案の質は、依然として実データで検証できていない。** F-3の承認フローは、Tier 1・Tier 2のいずれの提案にも同じように適用されるが、`show <id>`のConstitution注記は、Tierそのものの信頼度の違いを強調する仕組みにはなっていない(検証Tierの表示はあるが、「Tier 2はより慎重に見るべき」という明示的な警告は追加していない)——将来、Tier別にレビューUIの注意喚起を強めることを検討する余地がある。
4. **1日あたりのPR作成上限(`_MAX_DAILY_PRS = 3`)は、旧`self_improvement.py`の値をそのまま踏襲したが、この数値自体の妥当性(人間が実際にレビューできる分量として適切か)は、独自に再検証していない。** 実運用の中で、運用者の負荷に応じて調整することを想定している。
5. **`apply_unified_diff()`は、独自実装のため、LLMが生成する統一diffの、あらゆる書式のゆらぎ(例: ファジーマッチが必要なケース、行番号のオフセットがずれているケース)には対応していない。** 厳密な一致を要求するfail-closed設計(19.2節)であるため、承認時点から対象ファイルが変化していた場合や、LLMの出力が標準的な統一diff形式から多少ずれていた場合、`DiffApplyError`で失敗し、`pr_creation_status="failed"`として記録される(=黙って間違った内容をコミットすることは無いが、正当な差分が誤って失敗と判定される可能性はある)。実運用でこの失敗率が高い場合、既存のdiff適用ライブラリの導入を検討する価値がある。
6. **本タスクを含め、Phase D〜F全体を通じて、実モデルAPI(OpenAI advanced tier)・実Supabaseデータベースでの、エンドツーエンドの動作確認は、一度も行われていない。** 全ての検証は、LLM呼び出し・DB呼び出し・(F-3では)GitHub API呼び出しをモックした、ユニットテストレベルにとどまる——依頼書の一貫した注意事項(追加のAPIキー取得・サーバーアクセスを試みない)に従った結果であり、意図的な制約である。運用者が、実際の環境で一度、D-1(根拠収集)からF-3(PR作成)までを通しで実行し、パイプライン全体が意図通りに機能することを確認することを、Phase D〜F全体の完了にあたって、最も強く推奨する。

---

## 24. マージについて(依頼書の指示により、本タスクは確認を待つ)

「テスト・検証」章の要件をすべて満たしていることを確認した(未承認の差分が実行に進まないことの静的+動的な実測証明・承認された差分の正しいブランチ作成/コミット/PR作成シミュレーション・却下時の記録・既存テストの回帰確認、いずれも22章参照)。

**しかし、依頼書が明示的に指示した通り、本タスクはPhase D〜F全体の最終ステップであり、実際にGitHubへの書き込みに繋がる、最も重要な実装であるため、テストが全て通過した本時点でも、mainへは一切マージしていない。** ブランチ(`phase-f3-approval-and-pr-creation`)を作業ツリーに残し、コミット・プッシュした上で、本報告を運用者へ提示し、確認を得てからマージする。
