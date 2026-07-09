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

1. データセットを取得する(1章のコマンド)。**2026-07-09時点、このサー
   バー上の`backend/eval/bench_data/`には既に配置済み**(9章参照。新しい
   環境にセットアップし直す場合や、別バリアント[`_s`/`_m`等]を追加取得
   する場合は、以下のコマンドを再実行すればよい):
   ```bash
   cd backend
   mkdir -p eval/bench_data
   wget https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json -P eval/bench_data/
   wget https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json -P eval/bench_data/
   ```
   (`eval/bench_data/`は`.gitignore`済み — リポジトリには含めない設計。
   9章で理由を詳述)

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

## 8. Phase C-full-2: SB-3(記憶重複率)・SB-7(改善サイクル伸び率基盤)

対象ブランチ: `phase-c-full-2-sb3-sb7`(mainからfork)。

Phase C-mini(SB-1・SB-2・SB-4)・Phase C-full-1(公開ベンチマーク)に続き、
`sigmaris_roadmap.md`のSB-1〜7のうち残るSB-3(memory_duplicate_rate)を
実装し、SB-7(improvement_cycle_gain)は記録基盤のみを用意した。SB-5・
SB-6は測定対象の機能自体が存在しないため意図的に未実装のままとした。

### 8.1 SB-3の実装詳細

**重複の定義**: `user_fact_items`は`(user_id, category, key)`にUNIQUE
制約があるため、同一category/keyの行が2つ存在することはあり得ない。
ここで言う「重複」は、**異なるcategory/keyの行が実質的に同じ主張をして
いる**状態(例: 抽出時の判断揺れで、ある回は`preferences/favorite_
color`、別の回は`lifestyle/color_preference`として同じ「好きな色」が
別々の行に記録されるケース)を指す。この定義自体、B1のスキーマ
(UNIQUE制約)を読んで初めて明確になった、実装前提の確認事項である。

**B1との連携方法**: `search_fact_memory` RPC(B1のベクトル検索)は
「1つのクエリベクトル vs コーパス」の形にしか対応していないため直接は
呼べないが、そのRPCが使っている類似度の定義(`1 - cosine_distance`
= 標準的なコサイン類似度、`202607150037_time_aware_search.sql`で確認
済み)を、全ペア(コーパス vs コーパス自身)に適用する形でそのまま再利用
した。新しい類似度アルゴリズムは導入していない。具体的には:

1. `user_fact_data.get_fact_items_with_embeddings()`(新設)で、B1が
   既に生成・保存済みの`embedding`列(768次元pgvector)を含めて全アク
   ティブfactを1回のSELECTで取得する。**Phase BA2が`FACT_ITEM_SELECT`
   から`embedding`列を意図的に除外した**ことは把握した上で、この読み取
   りだけは例外的にembeddingを取得する必要があると判断した(判断根拠:
   BA2の除外は「どのgeneral-purpose callerもembeddingを読み返していな
   かった」ことが前提であり、SB-3はその前提が初めて崩れる、正当な例外
   ケースである。ホットパスではなく評価スクリプトからの、頻度の低い呼び
   出しであるため、BA2が避けようとした転送・パースコストの影響は許容範
   囲と判断した)。
2. `eval_metrics.compute_memory_duplicate_rate()`(新設、純粋関数)が、
   取得したembeddingどうしの全ペアのコサイン類似度をPython側で計算する
   (numpy等の新規依存は追加せず、標準ライブラリの`math`のみで実装)。
   類似度が閾値以上のペアをUnion-Findで連結成分(クラスタ)にまとめる。

**算出式の判断根拠**: 「全記憶に対する重複ペアの割合」ではなく、
**「完全に重複排除した場合に削除される件数の割合」**を採用した:
```
memory_duplicate_rate = Σ(クラスタサイズ - 1、サイズ2以上のクラスタのみ) / 総アクティブfact数
```
3件が相互に重複しているクラスタをペア単位(3ペア)で数えると、重複の
実態(「1件残せば済む」= 2件が無駄)より過大に見えてしまう。「このクラ
スタから1件だけ残せば済む」という無駄を数える方が、roadmap記載の目標
(「3%以下」)という**bounded[0,1)の比率**としての意図に近いと判断した。
分母はembeddingの有無を問わず全アクティブfactとした(embedding未生成分
は判定対象から除外されるため、実際より低い値が出る=安全側のバイアスで
あることを明記する。`update_fact_embeddings()`(B1既存)で事前にバック
フィルすることを推奨)。

**類似度の閾値**: `DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD = 0.92`
(`eval_metrics.py`)。B1の検索デフォルト閾値0.7は「このクエリと無関係で
はない」という緩い関連性の基準であり、「これは同じ事実の言い換えだ」と
いう、はるかに厳しい基準には流用できないと判断し、大きく引き上げた。
0.92という具体的な値自体は、実LLM/embedding環境での実測による検証はで
きていない(0章の制約と同じ)ヒューリスティックであり、見逃し(実際は重
複なのに検出できない)より誤検出(実際は別の事実なのに重複と判定してし
まう)を避ける、安全側に倒した選択である。実測後に調整の余地があること
を7章の申し送りに記載する。

**`run_eval.py`への統合**: `eval_runner.run_eval()`が
`get_fact_items_with_embeddings()`と`compute_memory_duplicate_rate()`を
呼び、結果を既存の返り値dictに追加(既存の`memory_f1_score`等の計算とは
独立、`asyncio.gather`で並行取得)。`run_eval.py`の標準出力に
`memory_duplicate_rate`を他の指標と並べて表示し、重複候補クラスタの一覧
(類似度降順、上位10件)も表示する。`eval_runs_store.record_eval_run()`
にも`memory_duplicate_rate`/`duplicate_fact_count`/
`duplicate_cluster_count`を追加した(マイグレーション
`202607210043_sigmaris_eval_runs_sb3.sql`、既存の`sigmaris_eval_runs`
テーブルへのALTER TABLE、未適用)。

**新規テーブルにしなかった理由**: Phase C-full-1の`sigmaris_bench_runs`
とは異なり、SB-3は`sigmaris_eval_runs`にそのまま列追加した。判断根拠:
SB-3は同じ`run_eval.py`の同じ実行の中で、同じアクティブfactスナップ
ショットに対して計算され、同じCLI出力行に他の3指標と並んで表示される
「もう1つの内部指標」であり、「社内指標 vs 対外的な客観ベンチマーク」
というC-full-1で新テーブルを切った理由(構造的に一目で区別できるように
する)に該当しない。

### 8.2 SB-7の記録基盤の設計詳細

指示書の要件通り、**呼び出し元(Phase Dの改良提案エンジン)は実装して
いない**。用意したのは以下の2点のみ。

1. **`improvement_cycle_metrics.compute_improvement_cycle_gain()`**
   (純粋関数、I/Oなし): 指標名をキーとする2つのスナップショット
   (before/after)を受け取り、単一の伸び率に集約する。SB-1・SB-2
   (高いほど良い)とSB-4・SB-3(低いほど良い)の**極性の違いを吸収**
   し、常に「正の値=改善」に正規化してから、対象となった指標の**単純
   平均**を`overall_gain_pct`とする。判断根拠: SB-1〜SB-6は単位・スケー
   ルがバラバラなため、パーセント変化という無次元量に揃えるのが最も単純
   で説明しやすい。重み付け(例: memory_f1_scoreを重視する等)は、実際
   に改善サイクルが動き出しグッドハート化の傾向等の知見が蓄積してから検
   討すべきであり、現時点で恣意的な重みを入れないことを優先した(判断根
   拠)。SB-5(`curiosity_relevance_score`)・SB-6
   (`self_diagnosis_accuracy`)の指標名は、対象機能が未実装であっても
   **極性(高いほど良い)だけは先に登録**しておいた — 将来これらが実装
   された際、この関数を変更せずにそのまま使えるようにするため。
2. **`improvement_cycle_store.py`**(`record_improvement_cycle()`/
   `get_recent_improvement_cycles()`、`sigmaris_eval_runs`/
   `sigmaris_bench_runs`と同じservice_role専用RLS・ベストエフォート書き
   込みパターン): `cycle_label`(変更の短い識別名)・
   `change_description`(変更内容の説明文)・`before_metrics`/
   `after_metrics`(指標スナップショット、jsonb)・`overall_gain_pct`・
   `metric_gains`(指標別内訳、jsonb)・`skipped_metrics`・`notes`を記録
   する。新規テーブル`sigmaris_improvement_cycles`
   (`202607210044_sigmaris_improvement_cycles.sql`、未適用)。

**jsonbカラムを選んだ理由**(`sigmaris_eval_runs`の固定列方式とは異な
る): SB-3のように将来的に指標の**種類自体が増える**(SB-5・SB-6が実装
された時点等)ことが分かっているテーブルであり、指標が増えるたびに
ALTER TABLEするより、jsonbでスナップショットごと保存する方が、Phase D
側の実装を待たずに将来のどんな指標セットにも対応できる。この設計判断は
マイグレーションファイル自体のコメントにも明記した。トレードオフとして
型付き列でのSQLクエリはできなくなるが、現時点でこのテーブルを
プログラム的にクエリするコードは存在しない(呼び出し元自体が未実装のた
め)ため、実害はないと判断した。

### 8.3 SB-5・SB-6の未実装理由の明記箇所

`docs/sigmaris/sigmaris_roadmap.md`の「C1. シグマリス独自指標」節
(SB-1〜7の一覧)に、各指標の実装状況(実装済み/意図的に未実装/基盤の
み用意済み)を直接注記する形で追記した。SB-5・SB-6については、対象機能
(Curiosity Engine、自己改良システムの自己診断機構)が存在しないため測
定しようがないこと、対象機能の実装時に別タスクとして着手すべきことを明
記し、リスト末尾に「指標一覧から欠けていることについて」という独立した
注記も加えた(将来「指標が抜けている」と問題視された際に、この経緯へた
どり着けるようにするため)。

### 8.4 テスト結果

`backend/tests/`には未コミット(既存方針を踏襲、スクラッチテストのみ)。
実モデルAPI・実Supabase接続へのアクセスは行っていない。

- **`compute_memory_duplicate_rate()`(11件)**: 意図的に重複させた埋め
  込みベクトル(コサイン類似度がほぼ1.0になるよう構成)で重複が正しく検
  出されること、重複のない(直交ベクトルの)テストデータで0に近い値
  (実際には厳密に0.0)を返すこと、3件が相互重複するクラスタが「2件の
  超過」として数えられること(ペア数の3ではない)、既定閾値(0.92)未満
  では検出されないこと・カスタム閾値が反映されること、embeddingが欠落
  した項目が母数には残るが判定対象からは除外されること、文字列エンコー
  ドされたembedding(PostgRESTからの想定される戻り値形式)が正しく
  パースされること、不正な文字列は「embeddingなし」として安全に扱われ
  ること、空入力・単一件でクラッシュしないことを確認した。
- **`compute_improvement_cycle_gain()`(10件)**: 高いほど良い指標・低い
  ほど良い指標それぞれで、改善時に正のpct_change、悪化時に負の
  pct_changeとなること(極性の吸収が正しいことの直接確認)、複数指標の
  単純平均が正しく計算されること、未登録の指標名・片側欠損・値がNone・
  beforeが0(ゼロ除算)がいずれもクラッシュせずskipped_metricsに記録さ
  れること、空スナップショットで0.0を返すこと、SB-5/SB-6の指標名が
  (未実装のままでも)極性登録済みで正しく計算できることを確認した。
- **`get_fact_items_with_embeddings()`(3件)**: `select`パラメータに
  `embedding`が含まれ`FACT_ITEM_SELECT`をベースにしていること、
  `active_only`の有無でフィルタが正しく切り替わること。
- **`improvement_cycle_store.py`(4件)**: レコードの書き込み・取得が正
  しいペイロード/パラメータで行われること、`SUPABASE_SERVICE_ROLE_KEY`
  未設定時に例外を投げず`None`を返すこと(要件2の「テストデータで正しく
  書き込み・読み込みできることを確認する」に対応)。
- **`eval_runner.run_eval()`とのSB-3統合(2件)**: 既存のC-mini指標
  (`memory_f1_score`等)が引き続き返り値に含まれること(要件4、回帰確
  認)、SB-3の各フィールドが正しい値で返り値に追加されていること。
- **`eval_runs_store.record_eval_run()`のSB-3拡張(2件)**: 新規引数が
  ペイロードに正しく含まれること、省略時は`None`で後方互換であること。
- **`run_eval.py`のCLI出力確認(1件)**: 実際のスクリプトの`_main()`を
  `--dry-run`で実行し、標準出力に`memory_duplicate_rate`・重複クラスタ
  一覧が実際に表示されることを確認した。

```
16 passed (既存の回帰テスト、backend/tests/、変更なし)
33 passed (本タスクの新規テスト)
= 49 passed
```

Phase BA2の`FACT_ITEM_SELECT`関連の既存スクラッチテスト(6件)も再実行
し、`user_fact_data.py`への変更(新規関数の追加のみ)が既存の`get_fact_
items`等に影響していないことを確認した。

### サンプル出力(モックデータでの実行結果)

```
評価実行中... testset=...\testset.json (1件)

============================================================
Phase C-mini 内部評価指標 (客観ベンチマークではない社内指標)
============================================================
testset_size       : 1 (評価対象 1件, skip 0件)
memory_precision    : 1.000
memory_recall       : 1.000
memory_f1_score     : 1.000
rag_ndcg_score      : 1.000
response_error_rate : 0.100  (直近7日, n=10)
memory_duplicate_rate: 0.333  (重複1件/1クラスタ, embedding有3/3件)
============================================================

重複候補クラスタ (1件、類似度降順):
  類似度1.000: ['fact-color-a', 'fact-color-b']

--dry-run のため sigmaris_eval_runs には記録していません。
```

（`fact-laptop`・`fact-color-a`・`fact-color-b`という3件のモック事実の
うち、後者2件を意図的に近似ベクトルにして重複として検出させたもの。
実際のスコアではない。)

### 8.5 気づいた懸念点・Phase D〜H着手時に参照すべき事項

1. **0.92という類似度閾値は未検証のヒューリスティック**(8.1節): 実際
   の285〜500件規模のembeddingで、この閾値がどの程度の重複を検出する
   か(過検出/過少検出のどちらに傾くか)は、運用者側の環境で
   `run_eval.py`を実行して初めて分かる。実測後、閾値の調整が必要になる
   可能性が高い。
2. **全ペア比較はO(N²)**: `compute_memory_duplicate_rate()`は現在の
   fact件数(数百件規模)では実用上問題ないと考えられるが、件数が数千
   件規模に増えた場合、Python側での全ペアコサイン類似度計算(現在は
   numpyなしの純粋Python実装)がボトルネックになりうる。B1のpgvector
   インデックス(ivfflat/hnsw等)を使った近似最近傍探索に切り替える、
   またはnumpyを導入してベクトル化する、といった最適化の余地がある
   (現時点では過剰実装と判断し、実装していない)。
3. **SB-7の重み付けは単純平均のまま**(8.2節): Phase Dが実際に動き出
   し、特定の指標が改善サイクルの評価においてグッドハート化しやすい
   (例: `memory_duplicate_rate`を下げるために正当な情報まで統合・削除
   してしまう等)ことが分かった場合、単純平均ではその指標の異常な変動が
   `overall_gain_pct`を歪める可能性がある。roadmapの二層評価
   (内部指標+外部ベンチマーク)という設計が、まさにこのリスクへの対策
   として既に用意されていることを、Phase D設計時に再確認すること。
4. **SB-3とSB-7の接続はまだ「配線」されていない**: `improvement_cycle_
   metrics.py`はSB-3を含む指標名を認識できるが、実際に`run_eval.py`の
   結果を`compute_improvement_cycle_gain()`に渡すコードはまだ存在しな
   い(Phase Dの改良提案エンジンが両者を橋渡しする想定)。Phase D設計時
   に、この2つのモジュールをどう接続するか(変更適用前後で`run_eval.py`
   相当を2回実行し、その結果をそのまま渡す、等)を具体的に設計する必要
   がある。
5. **2つの新規マイグレーションは未適用**: 指示書の注意事項通り、作成の
   みで適用は運用者側に委ねる
   (`202607210043_sigmaris_eval_runs_sb3.sql`・
   `202607210044_sigmaris_improvement_cycles.sql`)。前者が未適用の間
   は、`record_eval_run()`のSB-3フィールドを含むPOSTは失敗し、
   `run_eval.py`は「記録に失敗しました」という既存の分岐にフォールバッ
   クする(スコア自体の算出・表示には影響しない)。

---

## 9. データセットの実配置(2026-07-09)

Phase C-full-1完了後、実際に`run_longmemeval.py`/`run_locomo.py`を実行
しようとしたところ、`--input`に指定すべきデータセットファイルがこの
サーバー上のどこにも存在していないことが判明した(Phase C-full-1では
入手元・コマンド自体は1章に文書化していたが、実際のダウンロード・配置
はテスト用に一時的な作業ディレクトリ(スクラッチパス)で行っており、
リポジトリ内の本来の配置場所には置いていなかった)。本追記では、実際に
1章記載のコマンドでダウンロードし、`backend/eval/bench_data/`に配置した
上で動作確認を行った。

### 9.1 配置場所・入手手順

`backend/eval/bench_data/`(5.1節記載の想定位置と同一)に、1章記載の
コマンドをそのまま実行して配置した:

```bash
cd backend/eval/bench_data
curl -sL -o longmemeval_oracle.json "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json"
curl -sL -o locomo10.json "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
```

**実際に配置されたファイル**:

| ファイル | サイズ | 内容(実測) |
|---|---|---|
| `backend/eval/bench_data/longmemeval_oracle.json` | 15,388,478 bytes(約15.4MB) | 500インスタンス(1章の記載と一致) |
| `backend/eval/bench_data/locomo10.json` | 2,805,274 bytes(約2.8MB) | 10会話、合計1,986問(1章の記載と一致) |

ダウンロード後、`json.load()`で両ファイルが正しくパースできること、
件数が1章で報告した実測値と一致することを確認した(ファイル破損・
部分ダウンロードでないことの直接的な裏付け)。

### 9.2 gitで管理すべきか(判断・理由)

**判断: gitでは管理しない(`.gitignore`済みのまま、サーバー上にのみ配置
する)。** Phase C-full-1時点で既に`.gitignore`に`/backend/eval/bench_
data/`を追加済みだった(理由はそのコミットのコメントに記載済み)が、
実際にファイルが存在する状態になった今、その判断を再確認し、理由を改め
て整理する:

1. **LoCoMoはCC BY-NC 4.0であり、GitHubリポジトリへのコミットは「Share
   (共有)」に該当しうる**(1章参照)。運用者は個人利用・非商用と回答し
   ているため利用自体は問題ないが、リポジトリが将来公開される、共同作業
   者が増える等の状況変化があった場合に備え、**第三者データセットの
   生ファイルをリポジトリ本体に含めないのが最も安全**という判断は変わ
   らない。
2. **LongMemEval(MITライセンス)は法的な懸念はないが、それでも非推奨**:
   15.4MBという単一ファイルサイズは、コード変更の追跡を目的とするgit
   履歴に対して不釣り合いに大きく、かつ**このファイル自体が今後変更さ
   れることはない**(ダウンロードするたびに毎回同じ内容の第三者配布物)
   ため、バージョン管理のメリット(差分追跡)が一切ない。
3. **再現性は損なわれない**: 1章に記載した1行のダウンロードコマンドで
   誰でも同じファイルを再取得できる(ビルドが必要な生成物ではなく、単純
   な静的ファイルのダウンロード)。gitで管理しないことによる不利益は
   「初回セットアップ時にこのコマンドを実行する一手間」のみであり、
   5.1節の手順に既に明記されている。
4. 以上より、コードの変更履歴を追跡するgit と、頻繁には変わらない大きな
   第三者データを保持するファイルシステム(このサーバーの
   `backend/eval/bench_data/`)を分離する、標準的なMLデータセット管理の
   慣習に従うのが最も妥当と判断した。

### 9.3 `--dry-run`での動作確認結果

**認証情報なしでの実コマンド実行(ファイル読み込みの直接確認)**:
このセッションにはベンチマーク専用アカウントの認証情報
(`SIGMARIS_EVAL_BENCH_REFRESH_TOKEN`等)が設定されていない(0章と同じ
制約、新規に取得を試みていない)ため、実際のCLIコマンドをそのまま実行
すると、**ファイルの読み込み・件数表示までは成功し、その直後の認証
ステップで意図通り停止する**ことを確認した:

```
$ python scripts/run_longmemeval.py --input eval/bench_data/longmemeval_oracle.json --limit 3 --dry-run
LongMemEvalファイルを読み込みました: eval\bench_data\longmemeval_oracle.json (500 インスタンス)
--limit 3 により、先頭 3 件のみ実行します。
（この後、SIGMARIS_EVAL_BENCH_REFRESH_TOKEN未設定によりBenchAuthErrorで停止 — 想定通り)

$ python scripts/run_locomo.py --input eval/bench_data/locomo10.json --limit 1 --max-questions-per-instance 3 --dry-run
LoCoMoファイルを読み込みました: eval\bench_data\locomo10.json (10 会話)
--limit 1 により、先頭 1 会話のみ実行します。
--max-questions-per-instance 3 により、各会話の質問数を制限します。
実行対象: 1 会話、合計 3 問
（同様にBenchAuthErrorで停止 — 想定通り)
```

500インスタンス・10会話という件数が、9.1節の実測値と一致した状態で
正しく読み込まれ、`--limit`/`--max-questions-per-instance`も正しく
適用されていることが分かる。

**認証・LLM・DBをモックした完全なパイプライン実行(実データでの動作
確認)**: 6章と同様の手法(`bench_auth`のJWT/user解決と、LLM呼び出し・
DB呼び出しのみをモック、パイプラインのオーケストレーション自体はモック
しない)で、**今回配置した本物の完全なファイル**(6章のような抜粋
コピーではない)に対して実行し、正常に完走することを確認した:

```
LoCoMoファイルを読み込みました: eval\bench_data\locomo10.json (10 会話)
--limit 2 により、先頭 2 会話のみ実行します。
--max-questions-per-instance 4 により、各会話の質問数を制限します。
実行対象: 2 会話、合計 8 問
ベンチマーク専用アカウントで実行します (user_id=bench-user-id)

実行中... (2 会話)
  [conv-26] 4/4 正解
  [conv-30] 4/4 正解

============================================================
Phase C-full: LoCoMo (公開ベンチマーク・客観指標)
============================================================
conversations       : 2
total_questions     : 8
correct_count       : 8
overall_accuracy    : 1.000
------------------------------------------------------------
カテゴリ別正答率:
  multi_hop                    1.000  (2/2)
  open_domain                  1.000  (1/1)
  single_hop                   1.000  (1/1)
  temporal_reasoning           1.000  (4/4)
============================================================

--dry-run のため sigmaris_bench_runs には記録していません。
```

```
LongMemEvalファイルを読み込みました: eval\bench_data\longmemeval_oracle.json (500 インスタンス)
--limit 5 により、先頭 5 件のみ実行します。
ベンチマーク専用アカウントで実行します (user_id=bench-user-id)

実行中... (5 インスタンス、各1問)
  [gpt4_2655b836] 1/1 正解
  [gpt4_2487a7cb] 1/1 正解
  [gpt4_76048e76] 1/1 正解
  [gpt4_2312f94c] 1/1 正解
  [0bb5a684] 1/1 正解

============================================================
Phase C-full: LongMemEval (公開ベンチマーク・客観指標)
============================================================
instances           : 5
total_questions     : 5
correct_count       : 5
overall_accuracy    : 1.000
------------------------------------------------------------
カテゴリ別正答率:
  temporal_reasoning           1.000  (5/5)
============================================================

--dry-run のため sigmaris_bench_runs には記録していません。
```

6章と同じく、**正答率100%はLLM呼び出しをモックで固定した結果であり、
実際の記憶精度を表すものではない**。今回新たに確認できたのは、6章の
「実データの小規模抜粋」ではなく、**このサーバーに実際に配置された
完全なデータセットファイル(500インスタンス・10会話全体)に対して、
`--limit`/`--max-questions-per-instance`で範囲を絞った上で、ファイル
読み込みからスコア集計・CLI出力までが一気通貫で正常に動作する**ことで
ある。実際のベースラインスコアの取得(LLM呼び出しをモックせず、実
`SIGMARIS_EVAL_BENCH_REFRESH_TOKEN`・`OPENAI_API_KEY`等を用いた実行)は、
引き続き運用者側の環境で行う必要がある(5.1節の手順を参照)。

既存の`backend/tests/`(16件)も再実行し、本追記(データファイルの配置
のみ、コードの変更なし)による回帰がないことを確認した。

---

## Related Documents

- `docs/sigmaris/sigmaris_roadmap.md`(Phase C全体構成、C1/C2/C3節。
  Phase C-full-2でSB-1〜7それぞれの実装状況を追記済み)
- `docs/sigmaris/phase_c_mini_report.md`(Phase C-mini、内部指標との対比)
- `docs/sigmaris/phase_b_summary.md`(Phase B完了サマリー)
- Maharana et al., 2024, "Evaluating Very Long-Term Conversational Memory
  of LLM Agents" (arXiv:2402.17753) — LoCoMoの原論文、CC BY-NC 4.0の
  帰属表示要件に基づく引用
- Wu et al., 2024, "LongMemEval: Benchmarking Chat Assistants on
  Long-Term Interactive Memory" (arXiv:2410.10813) — LongMemEvalの原論文
