# Phase C-full-1 実施報告: LongMemEval/LoCoMo公開ベンチマークの導入

対象ブランチ: `phase-c-full-1-public-benchmarks`(mainからfork)

---

## 0. 着手前の確認: ライセンス懸念への対応

指示書の「マージについて」章が明示的に要求する通り、実装着手前にLoCoMoの
ライセンス条件を確認したところ、**CC BY-NC 4.0(非商用限定)**であること
が判明した(1章で詳述)。これは指示書自身が「作業を止めて報告し確認を
求めること」と明記している状況に該当すると判断し、実装に入る前に運用者
へ確認を求めた。「個人利用のみ、商用化の予定なし」との回答を得たため、
CC BY-NC 4.0の条件(非商用利用)を満たすと判断し、LongMemEval・LoCoMo
両方の実装を進めた。この経緯自体、判断根拠として本報告に残す。

---

## 1. データセットの入手元・ライセンス条件

### LongMemEval

- **公式配布元**: Hugging Face `xiaowu0162/longmemeval-cleaned`
  (GitHubリポジトリ`xiaowu0162/LongMemEval`のREADMEに記載された正式な
  配布先)。
- **ライセンス**: **MITライセンス**(GitHubリポジトリの`LICENSE`ファイル
  を直接取得し確認済み)。商用利用・再配布・改変いずれも制限なく許可され
  ている。
- **入手コマンド**:
  ```bash
  wget https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json
  wget https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json
  wget https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_m_cleaned.json
  ```
- **サイズ・件数**: `longmemeval_oracle.json`(証拠セッションのみを含む
  軽量版、今回のパイプライン検証で実際に使用)は約15.4MB、**500インスタ
  ンス**(1インスタンス=1質問+その質問専用のhaystackセッション群)。
  `_s`(約115kトークン相当・Llama3で約40セッション)・`_m`(約500セッシ
  ョン)は、より大きなhaystack(証拠セッション+大量のディストラクタ
  セッション)を含む、より現実的だが重いバリアント。
- **スキーマ**: `question_id`・`question_type`(single-session-user /
  single-session-assistant / single-session-preference /
  temporal-reasoning / knowledge-update / multi-session / abstention の
  7種)・`question`・`answer`・`question_date`・`haystack_dates`・
  `haystack_session_ids`・`haystack_sessions`(既にSigmarisと同じ
  `{"role": "user"/"assistant", "content": "..."}`形式)・
  `answer_session_ids`。

### LoCoMo

- **公式配布元**: GitHubリポジトリ`snap-research/locomo`の
  `data/locomo10.json`。
- **ライセンス**: **CC BY-NC 4.0(Attribution-NonCommercial 4.0
  International)**。リポジトリ直下の`LICENSE.txt`を直接取得し、条項を
  確認した(「reproduce and Share the Licensed Material...for
  NonCommercial purposes only」)。README自体には明示的なライセンス表記
  がなく、GitHubの自動ライセンス判定も`NOASSERTION`(自動検出不可)と表
  示されるため、ファイル一覧から`LICENSE.txt`を直接特定し、その内容を
  読んで確認した(0章で述べた通り、この確認結果を受けて運用者に利用方針
  を確認した)。**帰属表示(attribution)が必要**: Maharana et al., 2024,
  "Evaluating Very Long-Term Conversational Memory of LLM Agents"
  (arXiv:2402.17753)への引用を、本報告書・ソースコードのコメント双方に
  明記した。
- **入手コマンド**:
  ```bash
  wget https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json
  ```
- **サイズ・件数**: 約2.8MB、**10会話・合計1,986問**(実際にダウンロード
  して集計した実測値。`docs/sigmaris/sigmaris_roadmap.md`記載の
  「1,540問」とは一致しなかった — ロードマップ記載時点で参照していた
  バージョン・集計方法が異なる可能性があるが、本タスクでは実際にダウン
  ロードした現物のファイルの実測値を正としている)。LongMemEvalの
  「500問」はロードマップの記載と一致した。
- **スキーマ**: 1会話(`sample_id`)ごとに`conversation`(2話者
  `speaker_a`/`speaker_b`の実名+`session_N`/`session_N_date_time`の
  ペア、最大19セッション程度)と`qa`(その会話に紐づく質問群、1会話あた
  り最大約200問)。各QAは`question`・`answer`(または`adversarial_
  answer`)・`evidence`・`category`(1〜5の数値)を持つ。

### LoCoMoのカテゴリ数値の対応(独自に特定・裏付け)

論文本文の説明文(カテゴリ名の列挙順)だけでは、1〜5の数値とラベルの対
応が一意に特定できなかった(列挙順どおりに単純対応させると、実際の
コード・データと矛盾する)。次の2つの独立した根拠から対応を特定した:

1. **公式評価コード**(`task_eval/evaluation.py`)の採点分岐:
   `category == 1`のみ多段階回答の分割評価(→multi-hop)、
   `category in [2, 3, 4]`は単純F1評価、`category == 5`は
   「no information available」等の拒否表現の有無で判定(→adversarial)。
2. **実際にダウンロードしたデータのカテゴリ分布**: 1会話(conv-26)の
   分布(1=32件, 2=37件, 3=13件, 4=70件, 5=47件)と、全10会話合計の分布
   (1=282件, 2=321件, 3=96件, 4=841件, 5=446件)を突き合わせ、「4が最
   多・3が最少」という相対順序が両者で一致することを確認した。

この2つを突き合わせ、**1=multi_hop、2=temporal_reasoning、
3=open_domain、4=single_hop、5=adversarial**と特定した
(`backend/app/services/bench_datasets.py`の`_LOCOMO_CATEGORY_MAP`コメ
ントに根拠を明記済み)。

---

## 2. 記憶パイプラインへの投入方式・本番データとの分離方法

### 2.1 投入方式: 本番と同じ`memory_extractor.py`/`memory_search.py`をそのまま呼ぶ

独自の抽出・検索ロジックは一切実装していない
(`backend/app/services/bench_pipeline.py`)。

- **投入(ingest)**: `memory_extractor.extract_from_conversation()`を、
  各インスタンスのセッションを**時系列順**に、セッション単位(1セッシ
  ョンが大きい場合はさらに16メッセージ単位)で呼び出す。**判断根拠**:
  `extract_from_conversation`内部の`_format_conversation()`が
  `messages[-20:]`(直近20件)しか見ない実装になっていることをコードで
  確認した。1回の呼び出しで会話全体(LongMemEvalの複数セッション、
  LoCoMoの最大19セッション)をまとめて渡すと、直近20メッセージ以外が
  抽出されずに無視されてしまう。セッションごと(必要ならさらに16件ずつ)
  に分けて呼ぶことで、この既存の窓に収まる形で、かつ実際のチャットが
  時間をかけて蓄積していくのと同じ順序で投入する設計にした。
- **検索**: `memory_search.search_relevant_memories()`をそのまま呼び、
  本番のハイブリッド検索(embedding+trigram+B10リランク等、Phase B群の
  全ロジック込み)を経由する。

### 2.2 本番データとの分離: 専用のSupabase Authアカウント

`backend/app/services/bench_auth.py`。

**選択した方式**: `user_fact_items.user_id`は`auth.users(id)`への外部
キー制約があるため、任意のUUIDを発明することはできない。代わりに、
**海星さん本人とは別の、ベンチマーク専用のSupabase Authアカウントを1つ
作成**し、そのアカウントのJWT・user_idで全てのingest/検索/書き込みを行
う設計にした。

**この方式を選んだ根拠**(指示書が例示した「別のuser_idを使う」「テスト
専用のテーブルを使う」のうち、前者を採用した理由):
- テスト専用スキーマ/テーブルを別途用意する案も検討したが、その場合
  `search_relevant_memories()`(embedding類似度検索RPC等)をそのテーブル
  向けに作り直すか大幅にパラメータ化する必要があり、**「シグマリスの
  記憶パイプラインを評価する」という本来の目的から外れ、別物のパイプラ
  インを評価することになってしまう**。
- 既存のuser_id単位のRLS(`auth.uid() = user_id`)は、システム内の全
  テーブルで既に確立・検証済みの分離機構であり、「もう1人の(架空の)
  ユーザー」を追加するだけで、新しい分離ロジックを一切実装せずに完全な
  分離が得られる。

**セットアップ手順**(運用者が事前に1回行う必要がある、5章に詳述):
Supabaseダッシュボードでベンチマーク専用アカウントを作成し、そのユーザ
ーのrefresh_tokenを`.env`の`SIGMARIS_EVAL_BENCH_REFRESH_TOKEN`に設定す
る。本セッションでは実際にこのアカウントを作成できていない(0章で述べ
た通りSupabaseへのアクセス手段がない)ため、この手順自体は運用者側での
実施が必要。

**多層の安全機構**(いずれもテストで直接検証済み、6章参照):
1. `resolve_bench_user()`が、ベンチマークJWTから解決した`user_id`が、
   本番の`SIGMARIS_REFRESH_TOKEN`/`SIGMARIS_USER_JWT`から解決した
   `user_id`と一致しないかをクロスチェックする(設定ミス — 例えば誤っ
   て同じrefresh_tokenを両方の環境変数に設定してしまった場合 — を、
   ingestion開始前に検知して例外で止める)。
2. このクロスチェック自体が失敗した場合(本番側の認証情報が構成されて
   いない、ネットワーク障害等)は、実行をブロックしない(RLSが本来の安
   全機構であり、このチェックは多層防御の一つに過ぎないため)。
3. 各インスタンスの処理開始前に`wipe_bench_user_fact_items()`で
   `user_id=eq.{benchmark_user_id}`にスコープした`DELETE`を実行し、
   ベンチマークアカウントの`user_fact_items`を洗い流してから次のインス
   タンスを投入する。RLSにより、この`DELETE`はベンチマークJWTが持つ
   `auth.uid()`と一致する行しか原理的に削除できない。

### 2.3 インスタンス間の分離(本番データとの分離とは別の、もう一つの分離)

指示書には明記されていなかったが、実装過程で気付いた重要な設計判断
として、**「本番データとの分離」だけでなく「ベンチマーク内の異なるイン
スタンス間の分離」も必要**であることが分かった。

LongMemEvalは1レコード=1質問+専用haystackで、そもそも各インスタンス
は独立している。しかしLoCoMoは1会話(インスタンス)に対して最大約200問
が紐づいており、**もし全会話の記憶を同じuser_idに溜め込んでいくと、
会話Aについての質問が会話B〜Jの記憶も検索対象にしてしまい、公式の評価
プロトコル(各インスタンスの質問は、そのインスタンス自身のセッション
のみを対象に評価する)と異なる、無効な評価になってしまう**。

これを避けるため、2.2節の「洗い流し」を**インスタンスの切り替えごとに
毎回**実行する設計にした(`bench_pipeline.run_instance()`が
`wipe_bench_user_fact_items()`→ingest→質問応答、という順で1インスタン
スを完結させ、次のインスタンスに進む前に必ず洗い流す)。したがって
**インスタンスは並列実行できない**(同じ1つのベンチマークアカウントの
記憶状態を共有するため)。これは6章のテストで、複数インスタンスそれぞ
れについて洗い流しが個別に呼ばれることを直接確認した設計であり、7章で
本格実行時の速度面の懸念として改めて触れる。

---

## 3. 採点方式(LLM-as-a-Judge)

### 3.1 使用モデル: 新設の`TaskType.EVAL_JUDGE`(advanced階層)

`local_llm.py`に`TaskType.EVAL_JUDGE`を新設し、`settings.eval_judge_
model or settings.openai_advanced_model`(未設定時のデフォルトは
`gpt-5.5`)にマッピングした。`_LOCAL_TASK_TYPES`には**含めていない**
(`SELF_REFLECT`/`COMPLEX_REASONING`と同じ扱い、ローカルOllamaには一切
ルーティングしない)。

**判断根拠**(指示書要件: 「既存のTaskTypeルーティングに則って選定し、
判断根拠を報告に記載すること」):

- **既存の`TaskType.EVAL_GENERATION`(Phase C-mini、mini階層)を再利用
  する案も検討したが、採用しなかった。** 理由: LLM-as-a-Judgeの判定結
  果そのものが、この機能全体が報告する数値の正しさを直接左右する
  (判定が甘ければベンチマークスコアが実態より高く出て、対外的に主張
  できる客観指標というPhase C-fullの目的そのものが損なわれる)。これは
  「1件の質問・回答を1件生成する」C-miniのテストセット生成
  (`EVAL_GENERATION`)とは非対称なリスクであり、単に「評価まわりの
  LLM呼び出し」として同じ扱いにするのは適切でないと判断した。
- 同様の「判定の質そのものが成果物」という理由でより上位のモデル階層を
  選んでいる既存の前例として、`goal_alignment.py`(B16、決定と目標の
  ニュアンスのある比較判定)が`TaskType.SELF_REFLECT`(advanced階層)を
  使っていることを確認し、これに倣った。
- 独自の`settings.eval_judge_model`オーバーライドを新設し
  (`sigmaris_reflect_model`と同じパターン)、本格実行時にコストと精度
  のトレードオフを運用者が調整できるようにした(7章で詳述する通り、
  advanced階層での全数実行はコストが相応にかかりうるため)。

### 3.2 判定の流れ: 検索→回答生成→判定の3段階

`bench_pipeline.py`:

1. **検索**(`synthesize_answer`内): `search_relevant_memories()`で、
   質問文に対する関連記憶を本番と同じロジックで取得する。
2. **回答生成**(`synthesize_answer`): 取得した記憶のみを根拠として、
   簡潔な事実回答を1文で生成させる(`TaskType.EVAL_GENERATION`、
   `temperature=0.0`)。**シグマリスの人格・口調を経由する本番の
   `orchestrator`/`persona`パイプラインは通していない**(3.3節で理由を
   詳述)。
3. **判定**(`judge_answer`): 生成された回答と正解(`gold_answer`)を、
   `TaskType.EVAL_JUDGE`のLLMに比較させ、`{"correct": bool, "reasoning":
   str}`のJSONで判定を得る(`json_mode=True`、`temperature=0.0`)。
   言い回し・書式の違いには寛容(例:日付表記の違いは同一視)、事実内容
   には厳格、という指示をプロンプトに明記した。**adversarial(LoCoMo
   category 5・LongMemEval abstention)は判定ロジックを分岐**させ、
   「正解文言を確信をもって述べたら誤り、情報がない旨を述べれば正解」
   という逆の基準で判定させる(1章で確認した公式評価コードの分岐と同じ
   考え方)。

### 3.3 「記憶パイプライン」に評価範囲を絞った理由(本番の人格変換は経由しない)

LongMemEval/LoCoMoは元々「チャットアシスタントが正しく答えられるか」を
測るベンチマークだが、本実装ではシグマリスの`orchestrator`/`persona_
rewriter`(BA4で統合済みの人格生成)は経由せず、**取得した記憶からの
直接的な事実回答生成**にとどめた。**判断根拠**:

- ロードマップ・指示書のいずれも「シグマリスの**記憶パイプライン**
  (抽出→保存→検索→応答)」を評価対象として明記しており、この評価の
  焦点は記憶の抽出・保存・検索精度である。
- シグマリスの人格(`persona.md`)は「海星さんの家庭支援AI」という特定
  の会話スタイルを持ち、簡潔な事実確認への回答を意図的に外した応答
  (雑談的な相槌、確認質問の織り込み等)をすることがある。これをその
  まま公開ベンチマークの採点にかけると、**記憶精度ではなく人格スタイル
  の違いによって不当にスコアが下がる**リスクがある。
- 将来的に「人格込みのエンドツーエンド」評価をしたい場合は、
  `run_orchestrator_chat()`を丸ごと経由する別モードとして追加できる設
  計にしてある(現状の`synthesize_answer()`を差し替えるだけで済む)。
  7章の申し送り事項に記載する。

---

## 4. スコア記録の設計(C-miniとの区別)

新規テーブル`sigmaris_bench_runs`
(`supabase/migrations/202607200042_sigmaris_bench_runs.sql`、**未適用**)
を、Phase C-miniの`sigmaris_eval_runs`とは完全に別テーブルとして新設し
た。

**判断根拠**: 同じテーブルに列を追加する案(例: `sigmaris_eval_runs`に
`dataset`列を足して`internal`/`longmemeval`/`locomo`を区別する)も考え
られたが、採用しなかった。指示書の要件そのものが「明確に区別」であり、
**テーブルを分けることが、運用者が`sigmaris_eval_runs`/`sigmaris_bench_
runs`のどちらを見ているか一目で分かる、最も強い保証になる**と判断した。
列構成も異なる(`sigmaris_eval_runs`は`precision`/`recall`/`f1`/`ndcg`、
`sigmaris_bench_runs`は`overall_accuracy`+カテゴリ別内訳
`category_counts`/`category_accuracy`+`adversarial_accuracy`)ため、
無理に同じスキーマへ寄せる利点も薄いと判断した。

`sigmaris_eval_runs`と同じ`service_role_only`RLSパターン、同じ
「書き込み失敗は例外を投げず記録するだけ」という設計(`bench_runs_
store.py`)を踏襲している。

---

## 5. 実行方法

### 5.1 事前準備(初回のみ)

1. データセットを取得する(1章のコマンド):
   ```bash
   cd backend
   mkdir -p eval/bench_data
   wget https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json -P eval/bench_data/
   wget https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json -P eval/bench_data/
   ```
   (`eval/bench_data/`は`.gitignore`済み — ライセンス上の理由でリポジトリには含めない設計)

2. ベンチマーク専用のSupabase Authアカウントを作成する(2.2節参照)。
   Supabaseダッシュボード → Authentication → Users → 新規ユーザー作成。
   海星さん本人とは異なるメールアドレスを使うこと。

3. そのアカウントでサインインし、`/auth/v1/token?grant_type=password`
   で取得した`refresh_token`を`backend/.env`に設定する:
   ```
   SIGMARIS_EVAL_BENCH_REFRESH_TOKEN=<refresh_tokenの値>
   ```

4. マイグレーション`202607200042_sigmaris_bench_runs.sql`を適用する
   (未適用、運用者側での適用が必要 — 注意事項参照)。

### 5.2 実行コマンド

```bash
cd backend

# LongMemEval: 小規模な動作確認(先頭10インスタンスのみ)
python scripts/run_longmemeval.py --input eval/bench_data/longmemeval_oracle.json --limit 10 --dry-run

# LongMemEval: 本番記録あり
python scripts/run_longmemeval.py --input eval/bench_data/longmemeval_oracle.json --limit 10 --notes "初回動作確認"

# LoCoMo: 小規模な動作確認(先頭1会話・その会話の先頭5問のみ)
python scripts/run_locomo.py --input eval/bench_data/locomo10.json --limit 1 --max-questions-per-instance 5 --dry-run

# LoCoMo: 本番記録あり
python scripts/run_locomo.py --input eval/bench_data/locomo10.json --limit 1 --max-questions-per-instance 5 --notes "初回動作確認"
```

**全件実行(500インスタンス・約2,000問)は本タスクの範囲外**(指示書の
注意事項通り)。全件実行する場合は`--limit`/`--max-questions-per-
instance`を外すだけで良いが、7章のコスト面の懸念を先に確認すること。

---

## 6. 小規模テストでの実行結果

実モデルAPI・実Supabase接続へのアクセスは行っていない(0章と同じ制約)。
以下は全てモック環境での検証結果。ただし**入力データ自体は自作せず、実
際にダウンロードした本物のLongMemEval/LoCoMoファイルから抽出した小規模
サブセットを使用**した(指示書要件1を、テストの入力データにおいても
一貫させた)。

### テスト構成(計55件、全てPASS)

- `bench_datasets.py`のローダー(11件): 実データ(1章のサンプル)を
  用いて、LongMemEvalのセッションが日付文字列で正しく時系列ソートされ
  ること、LoCoMoの2話者が正しく話者名プレフィックス付きで`role="user"`
  に変換されること、カテゴリ対応(1章)が正しく適用されること等を確認。
- `bench_scoring.py`の集計ロジック(6件): 全体正答率・カテゴリ別正答
  率・adversarial正答率の計算、空入力時の扱い。
- `bench_auth.py`(9件): refresh_token/静的JWTの両経路、本番アカウント
  との衝突検知(2.2節の安全機構)とその意図的な失敗時の非ブロッキング
  挙動、洗い流しが正しいuser_idにスコープされること。
- `bench_pipeline.py`(15件): セッションのチャンク分割(20メッセージ窓
  を超える長いセッションが正しく分割されること)、抽出失敗が他のチャン
  クの処理を止めないこと、回答生成・判定それぞれのプロンプト構築とAPI
  異常系(非JSON応答・例外)の安全な縮退、インスタンス実行の順序
  (洗い流し→投入→質問応答)。
- `bench_runs_store.py`・`TaskType.EVAL_JUDGE`設定(7件)。
- **エンドツーエンド統合テスト(3件)**: `load_locomo_file`/`load_
  longmemeval_file`で実データの小サブセットを読み込み、`run_benchmark`
  →`aggregate_bench_results`まで一気通貫で実行(外部境界=LLM呼び出し・
  DB呼び出しのみモック、パイプライン自体のオーケストレーションはモック
  していない)。LoCoMoのadversarial問題の判定分岐、複数インスタンスで
  洗い流しがそれぞれ独立して呼ばれることも確認。
- **実際のCLIスクリプト(`run_locomo.py`/`run_longmemeval.py`)自体の
  実行テスト(4件)**: 実データから抽出した小規模ファイルを`--dry-run`
  で実際に読み込ませ、標準出力にスコアが正しく表示されること、DB書き込
  みがスキップされることを確認。

```
16 passed (既存の回帰テスト、backend/tests/、変更なし)
55 passed (本タスクの新規テスト)
= 71 passed
```

### サンプルスコア(実データ・モックLLMでの実行結果)

LoCoMo(conv-26、実際のセッション2件・実際の質問5件を使用、LLM呼び出し
はモック):

```
LoCoMoファイルを読み込みました: ...locomo_small_real.json (1 会話)
実行対象: 1 会話、合計 5 問
ベンチマーク専用アカウントで実行します (user_id=bench-user-id)

実行中... (1 会話)
  [conv-26] 5/5 正解

============================================================
Phase C-full: LoCoMo (公開ベンチマーク・客観指標)
============================================================
conversations       : 1
total_questions     : 5
correct_count       : 5
overall_accuracy    : 1.000
------------------------------------------------------------
カテゴリ別正答率:
  multi_hop                    1.000  (2/2)
  open_domain                  1.000  (1/1)
  temporal_reasoning           1.000  (2/2)
============================================================

--dry-run のため sigmaris_bench_runs には記録していません。
```

LongMemEval(oracleファイルの実際の先頭2インスタンス、LLM呼び出しはモック):

```
LongMemEvalファイルを読み込みました: ...longmemeval_small_real.json (2 インスタンス)
ベンチマーク専用アカウントで実行します (user_id=bench-user-id)

実行中... (2 インスタンス、各1問)
  [gpt4_2655b836] 1/1 正解
  [gpt4_2487a7cb] 1/1 正解

============================================================
Phase C-full: LongMemEval (公開ベンチマーク・客観指標)
============================================================
instances           : 2
total_questions     : 2
correct_count       : 2
overall_accuracy    : 1.000
------------------------------------------------------------
カテゴリ別正答率:
  temporal_reasoning           1.000  (2/2)
============================================================

--dry-run のため sigmaris_bench_runs には記録していません。
```

**これらの数値は、正答率100%となるようモック側の回答・判定を意図的に
「正解」に固定した検証結果であり、シグマリスの実際の記憶精度を表すもの
ではない。** 目的は0章・6章で述べた通り、パイプライン全体(データ読み込
み→洗い流し→投入→検索→回答生成→判定→集計→CLI出力)が実際のデー
タに対して壊れずに動作し、妥当な形式のスコアを返すことの確認である。
実際のベースラインスコアは、5章の手順で運用者側の環境から実行して初めて
得られる。

---

## 7. 気づいた懸念点・本格実行に向けた申し送り事項

1. **本格実行のAPIコスト**: LongMemEval 500インスタンス+LoCoMo約1,986
   問、それぞれ ingest(セッション数分のLLM呼び出し)+回答生成
   (`EVAL_GENERATION`、mini階層)+判定(`EVAL_JUDGE`、advanced階層)
   が発生する。特に判定をadvanced階層(`gpt-5.5`)に固定した3.1節の判断
   により、全数実行時のコストは相応になりうる。`settings.eval_judge_
   model`で安価なモデルに切り替えられるようにはしてあるが、精度との
   トレードオフになる点は運用者の判断が必要。
2. **インスタンスの逐次実行という制約**(2.3節): 単一のベンチマーク
   アカウントの記憶状態を使い回す設計上、インスタンスを並列実行できな
   い。LongMemEval 500インスタンス・LoCoMo 10会話(各最大約200問)を
   全て逐次実行すると、実行時間が長くなることが予想される
   (1問あたり検索+回答生成+判定の3回のLLM呼び出し、かつingestに
   セッション数分のLLM呼び出しが追加でかかる)。将来、複数のベンチマー
   ク専用アカウントをローテーションして並列化する等の高速化は、本タス
   クの範囲外として見送った。
3. **人格パイプラインを経由しない設計の妥当性**(3.3節): 記憶精度に評価
   範囲を絞る判断をしたが、これは「シグマリスの応答全体」の品質を測る
   ものではない。将来的にエンドツーエンドでの評価も必要になった場合の
   ための拡張ポイント(`synthesize_answer()`の差し替え)は用意してある
   が、実装はしていない。
4. **LongMemEvalの`_s`/`_m`バリアントは未検証**: 今回実際に構造を確認
   ・テストしたのは`_oracle`(証拠セッションのみ)のみ。`_s`/`_m`
   (大量のディストラクタセッションを含む、より現実的でより重い変種)
   も同じスキーマ(`load_longmemeval_file`がそのまま読めるはず)である
   ことをREADMEの記載から確認したが、実際にダウンロード・動作確認は
   していない(ファイルサイズがoracleよりさらに大きいため、本タスクの
   「小規模サブセット確認」の範囲では省略した)。本格実行前に、まず
   `_s`または`_m`で同様の小規模動作確認を行うことを推奨する。
5. **LoCoMoの`event_summary`/`observation`/`session_summary`フィールド
   は未使用**: `locomo10.json`には`qa`以外にもこれらの補助アノテーショ
   ンが含まれているが、今回の実装は`conversation`(セッション)+`qa`
   (QA)のみを使用した。ロードマップの記述(「単発・多段階・オープン
   ドメイン・時系列の記憶想起」)がQAタスクを指しているとの理解に基づく
   絞り込みであり、これらのフィールドを使う別タスク(イベント要約評価
   等)が将来必要になれば別途対応が要る。
6. **ロードマップ記載のLoCoMo問題数(1,540問)と実測値(1,986問)の
   不一致**: 1章で述べた通り、実際にダウンロードしたファイルの実測値を
   優先し、報告書ではそちらを正としている。ロードマップ側の数値の出典
   は本タスクでは確認できていない。
7. **`sigmaris_bench_runs`マイグレーションは未適用**: 指示書の注意事項
   通り、作成のみ行い適用は運用者側に委ねる。

---

## Related Documents

- `docs/sigmaris/sigmaris_roadmap.md`(Phase C全体構成、C1/C2/C3節)
- `docs/sigmaris/phase_c_mini_report.md`(Phase C-mini、内部指標との対比)
- `docs/sigmaris/phase_b_summary.md`(Phase B完了サマリー)
- Maharana et al., 2024, "Evaluating Very Long-Term Conversational Memory
  of LLM Agents" (arXiv:2402.17753) — LoCoMoの原論文、CC BY-NC 4.0の
  帰属表示要件に基づく引用
- Wu et al., 2024, "LongMemEval: Benchmarking Chat Assistants on
  Long-Term Interactive Memory" (arXiv:2410.10813) — LongMemEvalの原論文
