# Phase C-mini 実施報告: 最小評価基盤(B群のPDCAを回すための3指標)

**目的:** Phase B(記憶拡張機能群)を「1機能実装→測定→次」の小さなPDCAで進められるよう、着手前に最低限の測定手段(`memory_f1_score`・`rag_ndcg_score`・`response_error_rate`)を用意する。
**作業ブランチ:** `phase-c-mini-eval-baseline`(Phase A0〜A5がマージ済みの`main`から新規作成)
**範囲:** SB-3〜SB-7の実装・LongMemEval/LoCoMoの導入(Phase C-full)・Phase B(記憶拡張機能そのもの)には着手していない。

**前置き:** 指示書は`docs/sigmaris/sigmaris_roadmap.md`(v2)を根拠文書として参照しているが、**このファイルは現時点のリポジトリ内に存在しない**(`git log --all`でも見つからず)。おそらく別セッション・別ツールでの検討がまだこのリポジトリにコミットされていないと思われる。指示書自体は3指標の定義・実施内容・要件が自己完結して書かれていたため、roadmapファイルを探すために作業を止めることはせず、指示書の記述のみを根拠に実装した。roadmapが実際にコミットされた際は、本レポートの前提(特に1章「客観的ベンチマークではない」という位置づけ)と齟齬がないか確認することを推奨する。

---

## 0. 【最重要】実データ・実LLMでの検証ができなかったことについて

ローカル環境の`backend/.env`には`AGENT_SECRETS`・`LOCAL_LLM_ENABLED`・`OLLAMA_BASE_URL`・`OLLAMA_EMBED_MODEL`の4項目しかなく、`SUPABASE_SERVICE_ROLE_KEY`はおろか、本番Supabaseへの認証済みアクセスに使える`SIGMARIS_REFRESH_TOKEN`/`SIGMARIS_USER_JWT`も存在しない。`frontend/.env.local`にSupabaseのURLとpublishable(anon)キーはあるが、`user_fact_items`等はRLSで`auth.uid() = user_id`保護されており、anonキー単体(実ユーザーのログインセッションなし)では本番の285件のfact・decision_logへのアクセスは一切できない。加えてローカルのOllama(`http://localhost:11434`)には接続できず(`curl`で接続拒否を確認)、`OPENAI_API_KEY`も未設定のため、**実LLM呼び出しも一切できない**。

この制約は指示書が既に想定・許容している(「実モデルAPIでの確認ができない場合、それ自体は要件未達とはみなさない」「サーバーアクセスやAPIキーの追加取得を試みる必要はない」)。したがって、以下の方針で進めた:

- **パイプライン全体(テストセット生成ロジック・3指標の計算ロジック・記録ロジック・CLIスクリプト)は実運用でそのまま使える形で完全に実装した。**
- **実データに対する本番テストセット生成・実際のベースライン計測は実施できていない。** 4章で述べる通り、代わりに実際に本番へ投入済みの既知のシードデータ(`backend/scripts/seed_fact_memory.py`)を元にした少数の手作りテストセットで、パイプライン全体が壊れずに動作し、かつ妥当なスコアを返すことをモック検証した。
- **運用者(海星さん、または今後実DB・実LLMアクセスを持つセッション)が、本報告の6章の手順で実際のベースラインを計測する必要がある。**

これは「指標を作ったが動くかどうか自分では確認していない」という意味ではない。ロジック自体はモックで極めて詳細に検証済みであり(5章)、未検証なのは「本番の285件・実LLM生成質問に対して実際に走らせた結果の数値」のみである。

---

## 1. 重要な前提の実装への反映

指示書が強調する「客観的ベンチマークではない」という位置づけは、コード側にも以下の形で反映した:

- `eval_metrics.py`のモジュールdocstring冒頭に明記。
- `eval_runner.py`のモジュールdocstring冒頭に明記。
- `sigmaris_eval_runs`マイグレーションのコメントに明記。
- `run_eval.py`の標準出力の見出し自体に「(客観ベンチマークではない社内指標)」という文言を含めた(実行結果を見るたびに毎回目に入る場所に置くのが最も実効性があると判断した)。

---

## 2. テストセットの生成方法・件数・保存形式

### 生成方法: a) fact逆生成 + b) decision逆生成の組み合わせ(指示書が示す2方式を両方採用)

`backend/app/services/testset_gen.py::build_testset()`:

- **a) fact由来**: `user_fact_items`(`active_only=True`、`is_deleted=false かつ is_stale=false`)からランダムサンプリングし、LLM(`TaskType.EVAL_GENERATION`、後述)に「この事実を答えとする自然な質問文」を生成させる。正解は`"category/key"`形式(例: `"devices/laptop"`)。
- **b) decision由来**: `sigmaris_decision_log`から`superseded_by`が無い(=現在アクティブな)決定を対象に、LLMに「この決定内容を尋ねる質問文」を生成させる。

### b)方式についての重要な設計判断: 正解ラベルは決定IDではなく、決定が参照するfact idに解決する

`sigmaris_decision_log`には埋め込み(embedding)列が存在せず、`search_relevant_memories()`(=`search_fact_memory` RPC)は`user_fact_items`のみを検索対象とする。つまり**決定記録そのものは現状のRAG検索の対象外**であり、もし正解ラベルを決定IDのまま使うと、その設問は原理的に0点(recall=0)になり続け、「RAGの精度が低い」のではなく「そもそも検索対象にない」ことによる偽の低スコアが指標に混入してしまう。

これを避けるため、decision由来の設問は**その決定の`memory_refs`(Phase A3の`detect_and_record_decision`が記録した、決定の根拠となったfact idの配列)をfactの`category/key`に解決し、それを正解ラベルとして使う**設計にした。`memory_refs`が空の決定(=根拠fact不明で採点しようがない)は候補から除外する(`_build_decision_entries`)。これにより、decision由来の設問も「本当に検索できるはずのもの」だけがテストセットに入る。

### 正解ラベルの保存形式: UUID直書きではなく`"category/key"`文字列

正解は生成時点のfact idではなく`"category/key"`という安定した参照で保存し、実行時(`eval_runner.py::run_eval`)に現在の`user_fact_items`を引き直してid解決する。理由:

- `user_fact_items`は`(user_id, category, key)`にUNIQUE制約があり、`upsert_fact_item` RPCの衝突キーそのものでもある(`fact_memory.sql`参照)ため、この既存の意味的キーを再利用するのが最も自然。
- factが一度削除されて同じcategory/keyで再作成された場合でもテストセットを書き換えずに済む。
- UUIDの羅列よりも`"devices/laptop"`の方が人間がテストセットを読んでレビューする際に理解しやすい(3章の「人力レビュー可能な設計」という要件に直結)。

実行時に解決できなかった設問(該当factが現在存在しない)は採点せず`skipped_entry_ids`として結果に明示する(黙って0点にしてスコアを歪めない)。

### LLMタスク種別: `TaskType.EVAL_GENERATION`を新設

`local_llm.py::LLMRouter`の既存ルーティングパターン(Phase A3の`DECISION_DETECTION`が前例)にそのまま倣い、`TaskType.EVAL_GENERATION`を追加した。ローカル対象タスク集合(`_LOCAL_TASK_TYPES`)にも加え、OpenAIモデル階層ではnano階層(`ROUTING`/`MEMORY_EXTRACTION`/`SUMMARIZE`/`DECISION_DETECTION`と同じ)に分類した。テストセット生成は「短い定型文を1つ作るだけ」の軽量タスクであり、Phase A3のdecision detectionと性質が近いと判断した。

### 保存形式: リポジトリ内のJSONファイル(DBテーブルではなく)

`backend/eval/testset.json`(gitignore対象、後述)。DBテーブル(例: `sigmaris_eval_testset`)にしなかった理由:

1. **人力レビュー・修正のしやすさ**: テキストエディタで直接開いて読み書きでき、diffも取れる。DBテーブルだと専用のCRUD手段が要る。
2. **今回の環境制約との整合性**: 本章冒頭の通り、この環境ではSupabaseへの書き込み検証自体ができない。JSON形式なら、ファイルI/Oのロジックはローカルで完全に検証できる(5章)。
3. `reviewed: true`のエントリを再生成時に保持する、という「差分マージ」的な操作は、DBのUPSERTロジックを book keeping するよりファイル全体を読み書きする方が実装・検証ともに単純。

`backend/eval/testset.json`自体は`.gitignore`に追加した(本物のデータが生成されると実際の`user_fact_items`の内容 — 個人情報に準ずる — を含むため、`.env`と同様の理由でコミット対象から外している)。一方、**パイプライン動作確認用の`backend/eval/testset.example.json`(12件、手作り、`generated_by: "manual_example"`)はコミットしてある** — 詳細は4章。

### 件数

`generate_eval_testset.py`のデフォルトは`--max-facts 20 --max-decisions 10`(指示書の「20〜30件程度」に対応)。実際に生成される件数は、LLMが有効な質問文を作れた件数・decision側は`memory_refs`が解決できた件数に依存するため上限であって確定値ではない。

---

## 3. 3指標それぞれの計測ロジックの実装詳細

すべて`backend/app/services/eval_metrics.py`に純粋関数として実装(I/O一切なし、ロジックのみ)。

### `memory_f1_score`

設問ごとに`search_relevant_memories()`の返り値(id集合)と正解id集合の重なりからPrecision・Recallを算出し、F1を計算。**マクロ平均**(設問ごとに1票、正解件数の多寡で重み付けしない)でテストセット全体を平均する。

エッジケースの扱い(コード内コメントに判断根拠を明記):
- 正解が空 かつ 検索結果も空 → 1.0(害がなかったとみなす)
- 正解が空 かつ 検索結果が非空 → 0.0(正解不明のため判定不能=0点)
- 正解が非空 かつ 検索結果が空 → 0.0

### `rag_ndcg_score`

二値関連度(0/1、指示書の「全て同等でよい」を採用)によるNDCG。`IDCG`は`min(正解件数, 検索件数)`で正規化する。これにより、Precision/Recallでは区別できない「関連文書を何位に返したか」という順位の質を測れる(5章のテストケースで、Precision/Recallが同じでも1位に出すか3位に出すかでNDCGが変わることを確認済み)。

### `response_error_rate`

新規テストセット不要、既存の`agent_invocation_audit_logs`(Phase A0以前から存在)の`status`列を集計するのみ。**`'failed'`のみをエラーとしてカウントし、`'completed_with_fallback'`は含めない**という判断をした — フォールバックはしたが応答自体は返せている状態であり、完全な失敗(`'failed'`)とは区別すべきと考えたため。この判断はコード内コメント・本レポートの両方に明記した(指示書の要件通り)。

---

## 4. 計測結果の記録方式と、次回以降の実行手順

### 記録方式: 新規Supabaseテーブル`sigmaris_eval_runs`(推奨案の通り)

`supabase/migrations/202607060028_sigmaris_eval_runs.sql`(**未適用**、他のPhaseのマイグレーションと同様)。`sigmaris_decision_log`・`sigmaris_internal_state`と同じ「メタ/運用データなのでservice_role_only」というRLSパターンを踏襲した(ユーザー所有コンテンツではなくシグマリス自身の運用指標であるため、ユーザーJWTスコープのRLSではなくservice-role専用とした)。書き込みは`backend/app/services/eval_runs_store.py::record_eval_run()`が担い、`decision_log.py::log_decision()`と同じ「失敗しても例外を投げず`None`を返すだけ」という設計にした(マイグレーション未適用・`SUPABASE_SERVICE_ROLE_KEY`未設定の環境でも、スコアの計測・標準出力自体はクラッシュせず動作する)。

軽量な代替(ログファイル)を採らなかった理由: このリポジトリの既存の「記録」系は全て(`chat_threads`・`sigmaris_decision_log`・`agent_invocation_audit_logs`・`sigmaris_internal_state`)Supabaseテーブルに一貫しており、それに揃えることでPhase B以降で計測結果を可視化・分析する際にSQLで柔軟にクエリできる。今回の環境ではこのテーブルへの実書き込み検証はできていないが、`record_eval_run`のHTTPリクエスト構築ロジック自体は`decision_log.py`の既存パターンを踏襲しており、構造的なリスクは低いと判断した。

### 実行手順(次回以降)

```bash
cd backend

# 1. (初回、またはPhase Bで新しいfact/decisionが増えた際に再実行)
#    テストセットを生成・更新する。SUPABASE_SERVICE_ROLE_KEY等の実クレデンシャル、
#    かつ実LLM(OpenAI or 疎通可能なOllama)が必要。
python scripts/generate_eval_testset.py

# 生成された backend/eval/testset.json を目視確認し、必要なら手で修正のうえ
# 該当エントリに "reviewed": true を付ける(次回generate実行時に上書きされなくなる)。

# 2. Phase Bの機能を1つ実装するたびに実行する。
python scripts/run_eval.py --notes "B1: ○○実装後"

# DBに記録せず数値だけ確認したい場合:
python scripts/run_eval.py --dry-run
```

`run_eval.py`は実行のたびに`sigmaris_eval_runs`の直近1件を取得し、各指標の差分(前回比)を標準出力に併記する(要件2「過去の実行結果と比較できること」への対応)。

---

## 5. テスト結果(モックベース、0章参照)

### `eval_metrics.py`(純粋関数)の検証

DB・LLM一切不要のロジックのみのテスト。8ケース全てPASS:

```
PASS: perfect match -> P=R=F1=NDCG=1.0
PASS: zero overlap (irrelevant results) -> P=R=F1=NDCG=0.0 (correctly low)
PASS: NDCG rewards ranking (first=1.000 > last=0.500), while precision/recall stay identical (0.333/1.000)
PASS: empty relevant + empty retrieved -> trivially perfect (no harm done)
PASS: aggregate macro-averages across queries (f1=0.500)
PASS: response_error_rate = 0.2 over n=10 (2 failed / 10 total)
PASS: empty audit log window -> error_rate=0.0, sample_size=0 (no crash)
PASS: completed_with_fallback excluded from error count (rate=0.167)
```

2つ目のケースが、指示書が要求する「意図的に関連性の低い記憶しか返らないケースでスコアが適切に低く出ることの確認」に直接対応する。3つ目のケースは、Precision/Recallが同一でもNDCGが順位を正しく反映することを示している。

### `eval_runner.run_eval()`のモック検証(`search_relevant_memories`・`get_fact_items`・監査ログ取得をモック)

```
PASS: good retrieval -> f1=1.0, ndcg=1.0, error_rate=0.1, skipped=['q-missing-fact']
PASS: bad/irrelevant retrieval -> f1=0.0, ndcg=0.0 (correctly low, not crashed, not falsely high)
```

「正解factが今のuser_fact_itemsに見つからない設問はskipされ、黙って0点として平均に混ざらない」という2章の設計(`skipped_entry_ids`)も、1つ目のケースで直接検証している。

### `testset_gen.build_testset()`のモック検証(LLM呼び出し・DB取得をモック)

```
PASS: generated 4 entries, decision without memory_refs excluded, decision with memory_refs resolved to fact key
PASS: reviewed:true entries are preserved verbatim and not re-generated/duplicated
```

2章で述べた「`memory_refs`が空のdecisionは除外する」設計と、「`reviewed: true`のエントリは再生成時に上書きされない」設計の両方を直接検証している。

### CLIスクリプト全体(`run_eval.py`)のエンドツーエンド・モック検証

`run_eval.py`の`_main()`を、ネットワーク層(`get_sigmaris_jwt`・`get_current_user`・`search_relevant_memories`・`get_fact_items`・監査ログ取得・`get_recent_eval_runs`)のみモックした状態で、**実際にコミットする`backend/eval/testset.example.json`(12件)に対して実行**した。要件1(「コマンド一つで3指標が計測でき、数値が出力される」)の直接的な証拠として、標準出力をそのまま転記する:

```
評価実行中... testset=...\backend\eval\testset.example.json (12件)

============================================================
Phase C-mini 内部評価指標 (客観ベンチマークではない社内指標)
============================================================
testset_size       : 12 (評価対象 12件, skip 0件)
memory_precision    : 0.917
memory_recall       : 0.819
memory_f1_score     : 0.847
rag_ndcg_score      : 0.917
response_error_rate : 0.000  (直近7日, n=10)
============================================================

--dry-run のため sigmaris_eval_runs には記録していません。
```

**この数値はPhase Bの基準点(実際のベースライン)ではない。** モックした検索関数が「質問文に特定のキーワードが含まれていれば正解を返す」という単純な模擬実装であり、本物の`search_relevant_memories`(埋め込みベクトル類似度検索)の精度を反映したものではない。目的はあくまで「パイプライン全体が壊れずに動き、0〜1の妥当な範囲の数値を返す」ことの確認である(0章参照)。

### 既存テスト

`backend/tests/`(8件)全てPASS。`import app.main`成功。新規追加した6ファイル(`eval_metrics.py`/`eval_runner.py`/`eval_runs_store.py`/`testset_gen.py`/`scripts/run_eval.py`/`scripts/generate_eval_testset.py`)は`py_compile`で構文エラーがないことも確認済み。

---

## 6. 実際に計測した初回のスコア(ベースライン)について

**未計測。** 0章で述べた通り、実際の285件のfact・実LLMへのアクセスがこの環境には一切ない。5章の数値はモックによるパイプライン動作確認であり、Phase Bの基準点として使えるものではない。

**運用者(海星さん、または実クレデンシャルを持つ今後のセッション)にお願いしたいこと:**

1. `backend/.env`に`SUPABASE_SERVICE_ROLE_KEY`・`SIGMARIS_REFRESH_TOKEN`(または`SIGMARIS_USER_JWT`)・(`LOCAL_LLM_ENABLED=false`の場合)`OPENAI_API_KEY`が揃っている環境(本番サーバー等)で、`python scripts/generate_eval_testset.py`を実行してテストセットを生成する。
2. 生成された`backend/eval/testset.json`の中身(特にLLMが生成した質問文の自然さ)を一度目視確認する(1章・2章で述べた「LLM自動生成の限界」への対処)。
3. `python scripts/run_eval.py --notes "Phase C-mini直後・Phase B着手前のベースライン"`を実行する。これが`sigmaris_eval_runs`に記録される最初の行になり、以降のPhase B各機能の効果測定の基準点になる。
4. マイグレーション`202607060028_sigmaris_eval_runs.sql`を他の未適用分と合わせて適用する(`python3 scripts/apply_migration.py 202607060028`)。

---

## 7. Phase A5で申し送りされた「embeddingのモデル由来混在リスク」が、今回の計測結果に影響していそうか

**この環境では観察できなかった。** 実際に本番の`search_relevant_memories`を呼んでいないため、Ollama製とOpenAI製のembeddingが混在した状態でのスコアへの影響は実測できていない。

ただし設計面から言えることが1つある: `memory_f1_score`・`rag_ndcg_score`は「前回計測との差分」を見る運用を想定した指標であり、**もし本番運用中に`LOCAL_LLM_ENABLED`の値やOllamaの疎通状態が切り替わるタイミングがあれば、その前後でスコアが変動しても、それはPhase Bの機能自体の効果ではなく、Phase A5で申し送りしたembeddingモデル由来混在の影響である可能性がある**。運用者が6章の手順でベースラインを取る際は、その時点の`LOCAL_LLM_ENABLED`の値と、Ollamaが実際に疎通していたかを`run_eval.py --notes`に書き残しておくことを推奨する(`sigmaris_eval_runs.notes`列はこの用途のために自由記述にしてある)。

---

## 8. 気づいた懸念点・Phase B群の実装に影響しそうな発見

1. **`sigmaris_decision_log`はベクトル検索の対象外である**ことが、今回改めて明確になった(2章)。もしPhase Bで「決定事項も記憶として検索できるようにする」という機能を検討する場合、`sigmaris_decision_log`にembedding列を追加し`search_fact_memory`相当のRPCを別途用意するか、`user_fact_items`と統合スキーマにするかの設計判断が必要になる。今回のPhase C-miniはこの制約を前提として設計を回避した(decisionの正解ラベルをfactに解決する)だけであり、根本的な解決はしていない。
2. **`response_error_rate`は現状ユーザー単位でしか集計できない設計にした**(`agent_invocation_audit_logs`の`user_id`フィルタが必須)。このシステムは実質シングルユーザー運用(海星さん本人のみ)であるため実害はないが、将来複数ユーザー化する場合はこの前提を見直す必要がある。
3. **`memory_f1_score`/`rag_ndcg_score`は`search_relevant_memories`の`limit`パラメータ(デフォルト5)に依存する**。Phase Bで検索件数の既定値自体を変更する機能を実装した場合、その変更前後でこの指標を比較すると「検索精度が変わった」のか「検索件数が変わっただけ」なのか区別できなくなる。`run_eval.py --search-limit`で固定できるようにしてあるので、比較する際は毎回同じ値を明示することを推奨する(デフォルト値のまま使い続けるのが安全)。
4. **テストセットの主要データソースである`seed_fact_memory.py`のFACT_ITEMSは、実際に本番へ投入された初期24件のみを表しており、現在の285件のうちの一部でしかない**。`generate_eval_testset.py`を実際に実行すれば全285件からサンプリングされるため問題にはならないが、もし当面`testset.example.json`(12件、初期シードデータのみが対象)を仮運用に使ってしまうと、Phase A3以降にチャット経由で蓄積された大部分のfactがテストセットの評価範囲に一切含まれないことになる。**`testset.example.json`は本番のベースラインとしては使わないこと**(4章・6章で強調した通り)。

---

## Related Documents

- [phase_a5_report.md](phase_a5_report.md) — 7章で触れたembeddingモデル由来混在リスクの発端
- [phase_a_summary.md](phase_a_summary.md) — Phase A0〜A5の全体サマリー
