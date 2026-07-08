# 緊急調査報告: `/chat`応答速度低下の原因調査

**本タスクはコードの変更を一切行っていない。調査・報告のみ。** 本番の記憶データ
への書き込み・削除も一切行っていない(読み取りコードの確認のみ)。

---

## 0. 調査方法と、この報告の確度についての明記

本調査は、実際のコード(`backend/app/services/orchestrator/service.py`・
`backend/app/services/chat.py`・`backend/app/services/orchestrator/
persona_rewriter.py`・`backend/app/services/orchestrator/schedule_agent_
client.py`・`backend/app/services/memory_search.py`・`backend/app/services/
chat_routing.py`・`backend/app/services/chat_prompts.py`・`backend/app/
services/app_profile_data.py`・`backend/app/services/app_chat_data.py`等)を
実際に読み、各処理が**直列か並列か**をコードの構造から確定させたものである。
この部分(3章の「構造」に関する記述)は**事実として確定**している。

一方、各処理の**所要時間そのもの**については、運用者が本タスクの依頼文に貼り
付けた2つの集計値(DB読み取り群が21:35:25.036〜21:35:26.871の約1.8秒、リクエ
スト全体で約6秒)以外の生ログ(`journalctl`の生の行・各行のタイムスタンプ)に
は、本セッションではアクセスできていない。サーバーへのSSH・実APIキーは本セッ
ションを通じて一切得られておらず、依頼文にも追加取得を試みないよう明記されて
いるため、**3章の秒数はコードの構造(どの呼び出しが何回・どの順序で発生する
か)と、貼り付けられた2つの集計値から逆算した「推定」であり、実測ではない**。
この点は3章で改めて明記する。「一時的なログ追加」についても、実際のサーバーに
デプロイして観測する手段がないため実施していない。

---

## 1. リクエスト処理フロー全体の図

`/chat`が実際にヒットするのは`POST /api/orchestrator/chat/stream`
(`backend/app/routes/orchestrator.py:54`)である。このエンドポイントから応答
のストリーミングが実際に開始されるまでの全処理を、層を区別せず時系列で示す。

```
POST /api/orchestrator/chat/stream  (routes/orchestrator.py)
  └─ run_orchestrator_chat_stream()  (orchestrator/service.py:972-)
      │
      ├─ [並列 gather ×10] ─────────────────────────────────────────────
      │   1. get_current_user(jwt)                         … 既存実装
      │   2. _cached_user_profile → get_user_profile        … 既存実装(TTLキャッシュ有)
      │   3. _cached_self_model → get_self_model            … 既存実装(TTLキャッシュ有)
      │   4. _cached_preference_patterns                     … Phase B14(TTLキャッシュ有)
      │   5. _cached_current_and_previous_topic              … Phase B6(TTLキャッシュ有)
      │   6. _cached_threshold_adjustment                     … Phase B15(TTLキャッシュ有)
      │   7. _cached_goal_alignment_flags                     … Phase B16(TTLキャッシュ有)
      │   8. _cached_entities_and_relations                   … Phase B9(TTLキャッシュ有)
      │   9. _cached_active_trends                             … 既存実装(trend_analyzer、TTLキャッシュ有)
      │  10. _prepare_session_messages()                       … Phase A1 ★このブランチだけ内部が直列★
      │        ├─ _ensure_chat_thread → get_chat_thread(1回目) … 既存実装
      │        └─ get_recent_messages_across_threads
      │             └─ get_profile_context(jwt)  ★キャッシュなし★
      │                   ├─ get_current_user(jwt)  ← "auth/user" 1回目はここではなくブランチ1、
      │                   │                            こちらは"auth/user"のもう1回分の候補
      │                   ├─ rest_select("profiles")
      │                   └─ rest_select("saved_locations")
      │             └─ rest_select("chat_messages")
      │  (この10本の中で唯一#10だけが内部に5段の直列チェーンを持つため、
      │   gather全体の所要時間は実質的に#10の直列チェーンの長さで決まる)
      │
      ├─ _cached_fact_items(jwt, user_id)                     … 既存実装+B17拡張 ★gather後・直列★
      │     (RLS経由で0件ならservice-role経由に再試行 = 最大2回直列読み取り)
      │
      ├─ start_invocation()  (audit.py)                        … 既存実装 ★直列・DB書き込み★
      │
      ├─ _build_memory_context()                                ★直列・この中に新規LLM呼び出しが2つ★
      │     ├─ build_entity_hint()                              … Phase B9(LLM呼び出しなし、文字列処理のみ)
      │     └─ search_with_decomposition()
      │           ├─ decompose_query()                          … Phase B7 ★新規LLM呼び出し★
      │           └─ search_relevant_memories()
      │                 ├─ [並列] generate_embedding() ‖ trgm検索RPC  … 既存実装(Phase A5/B1)
      │                 ├─ vector検索RPC                              … 既存実装(B1) ★直列(embeddingに依存)★
      │                 └─ rerank_candidates()                        … Phase B10 ★新規LLM呼び出し(条件付き)★
      │
      ├─ call_schedule_agent_stream()  ★HTTP経由(実ネットワークホップ)★
      │     └─ POST {base_url}/api/agent/chat/stream  (routes/agent.py:154)
      │           └─ stream_chat_completion_ui()  (services/chat.py:717-)  … 既存実装
      │                 ├─ get_chat_thread(2回目)                    … 既存実装
      │                 ├─ get_chat_thread_version()                  … 既存実装(Phase A4)
      │                 ├─ get_profile_context(jwt)  ★再度・キャッシュなし★
      │                 │     ├─ get_current_user(jwt)  ← "auth/user" 2回目
      │                 │     ├─ rest_select("profiles")            ← 2回目
      │                 │     └─ rest_select("saved_locations")      ← 2回目
      │                 ├─ extract_latest_image_contexts()
      │                 ├─ classify_chat_intent()                    … 既存実装 ★ヒューリスティックで
      │                 │                                              スキップされない場合、新規LLM呼び出し★
      │                 └─ client.responses.create(stream=True)       … 既存実装 ★本体応答生成(LLM)★
      │                       (ツール呼び出しがあれば最大8回ループ、都度execute_tool()を直列await)
      │
      │  ↑ ここまでの schedule_text は orchestrator 側で「蓄積されるだけ」で
      │    ユーザーには一切ストリームされない(tool_eventのみ即時中継)
      │
      ├─ rewrite_with_persona_stream()                           … 既存実装 ★新規の完全に別のLLM生成★
      │     (schedule_text 全文が揃ってから初めて呼ばれる。
      │      ここで生成される delta が初めてユーザーに見える文字になる)
      │     └─ compare_semantic_entities()                        … 既存実装 ★リライト完了後のLLM呼び出し★
      │           (ユーザーへのストリームは既に完了済みだが、doneイベント発火前に直列で発生)
      │
      ├─ finish_invocation()                                      … 既存実装 ★直列・DB書き込み★
      │
      ├─ get_inquiry_question()  (最大2秒タイムアウト)              … Phase B3 ★直列・応答文言に追記★
      │
      └─ [fire-and-forget、応答は既に返却済み] ─────────────────────────
            ├─ _extract_facts_bg()                                 … 既存実装+B2拡張
            └─ _cognitive_layer_bg()                                … A3/B2/B3/B6/B15/B16 (6並列)
```

**ユーザーが最初の文字を目にするまでに、少なくとも次の3つの完全に独立した
LLM生成が直列で発生しうる**: ①(質問が複合的な場合のみ)B7の`decompose_query()`
+条件付きB10の`rerank_candidates()`、②chat.pyの`classify_chat_intent()`(ヒュ
ーリスティックでスキップされない場合)、③chat.pyの本体応答生成
(`client.responses.create(stream=True)`)。さらに、**③の生成結果は
orchestrator層で一旦全文蓄積されるだけでユーザーには送信されず**、④
`rewrite_with_persona_stream()`という**別の完全なLLM生成**が③の完了後に開始
されて初めて、その最初のdeltaがユーザーに届く。つまり実質4段のLLM生成が直列に
連なっており、しかもその半分(③と④)は`/chat`アーキテクチャそのもの(Phase A
・Bいずれでもない、既存実装)に起因する。

---

## 2. 各処理の発生源一覧

| 処理 | ファイル:関数 | 発生源 | 並列/直列 | 毎ターン必須か |
|---|---|---|---|---|
| `get_current_user`(1回目) | `supabase_rest.py` | 既存実装 | 並列(gather内) | 必須 |
| `get_user_profile` | `user_fact_data.py` | 既存実装 | 並列(gather内、TTLキャッシュ有) | 必須 |
| `get_self_model` | `self_model.py` | 既存実装 | 並列(gather内、TTLキャッシュ有) | 必須ではない(日次更新) |
| `get_active_preference_patterns` | `decision_log.py` | **Phase B14** | 並列(gather内、TTLキャッシュ有) | 必須ではない(週次更新) |
| `get_current_and_previous_topic` | `topic_tracker.py` | **Phase B6** | 並列(gather内、TTLキャッシュ有) | 必須ではない(ターン単位で変わるが読み取り自体は軽い) |
| `get_threshold_adjustment` | `abstention_feedback.py` | **Phase B15** | 並列(gather内、TTLキャッシュ有) | 必須ではない |
| `get_active_goal_alignment_flags` | `goal_alignment.py` | **Phase B16** | 並列(gather内、TTLキャッシュ有) | 必須ではない(週次更新+14日クールダウン) |
| `get_entities_and_relations` | `knowledge_graph.py` | **Phase B9** | 並列(gather内、TTLキャッシュ有、2テーブル読み取り) | 必須ではない(週次更新) |
| `get_active_trends` | `trend_analyzer.py` | 既存実装 | 並列(gather内、TTLキャッシュ有) | 必須ではない |
| `get_chat_thread`(1回目) | `app_chat_data.py`(`_ensure_chat_thread`経由) | **Phase A1**が呼び出し元 | 直列(gather内の1ブランチ内) | 必須 |
| `get_recent_messages_across_threads` | `app_chat_data.py` | **Phase A1** | 直列(同上、内部に`get_profile_context`のフルチェーンを含む) | 必須 |
| `get_profile_context`(1回目、`auth/user`含む) | `app_profile_data.py` | 既存実装(A1から呼ばれる) | **直列・キャッシュなし** | 必須だが**重複**(3章参照) |
| `_cached_fact_items`(最大2回直列) | `user_fact_data.py` | 既存実装+**Phase B17**拡張 | gather後・直列 | 必須 |
| `start_invocation` | `orchestrator/audit.py` | 既存実装 | 直列・DB書き込み | 必須(監査ログ) |
| `build_entity_hint` | `knowledge_graph.py` | **Phase B9** | 直列だがLLM呼び出しなし(文字列処理のみ) | 必須ではない |
| `decompose_query` | `multihop_search.py` | **Phase B7** | 直列 ★新規LLM呼び出し★ | 必須ではない(分解判定自体は毎回走るが、大半は「分解不要」で終わる軽い判定) |
| `generate_embedding` ‖ trgm検索 | `memory_search.py` | 既存実装(A5/B1) | 並列(2者間) | 必須 |
| vector検索RPC | `memory_search.py` | 既存実装(B1) | 直列(embeddingに依存) | 必須 |
| `rerank_candidates` | `memory_rerank.py` | **Phase B10** | 直列 ★新規LLM呼び出し(候補数が上限以下なら自動スキップ)★ | 条件付き |
| HTTP hop → `/api/agent/chat/stream` | `schedule_agent_client.py` | 既存実装 | 直列(実ネットワークホップ) | 必須 |
| `get_chat_thread`(2回目)+`get_chat_thread_version` | `chat.py`→`app_chat_data.py` | 既存実装 | 直列・**1回目と重複** | 必須だが重複 |
| `get_profile_context`(2回目、`auth/user`含む) | `chat.py`→`app_profile_data.py` | 既存実装 | **直列・キャッシュなし・完全重複** | 3章参照 |
| `classify_chat_intent` | `chat_routing.py` | 既存実装 | 直列 ★条件付き新規LLM呼び出し★ | ヒューリスティックでしばしばスキップ |
| 本体応答生成(`client.responses.create`) | `chat.py` | 既存実装 | 直列 ★LLM生成・最大8回ツールループ★ | 必須 |
| `rewrite_with_persona_stream` | `persona_rewriter.py` | 既存実装 | 直列 ★完全に別のLLM生成★ | 必須(persona変換) |
| `compare_semantic_entities` | `response_guard.py`経由 | 既存実装 | 直列 ★LLM呼び出し★ | 必須(整合性検証) |
| `finish_invocation` | `orchestrator/audit.py` | 既存実装 | 直列・DB書き込み | 必須 |
| `get_inquiry_question` | `active_inquiry.py` | **Phase B3**(既存の質問フレームワークを拡張) | 直列(最大2秒) | 必須ではない |
| `_extract_facts_bg` / `_cognitive_layer_bg` | 各種 | A3/B2/B3/B6/B15/B16 | fire-and-forget(応答後) | 応答速度に**影響しない** |

---

## 3. ボトルネックの定量評価(推定であることの明記つき)

### 3.1 「DB読み取り群 約1.8秒」の内訳(構造は確定、内訳秒数は推定)

運用者のログにある14〜15個のテーブル名は、実際には**10本の並列ブランチ**に分
散しているが、そのうち**9本は単発の読み取りで軽い**(TTLキャッシュ付きの
Phase B群読み取りを含む)。**1本(`_prepare_session_messages`、Phase A1)だ
けが内部に最大5段の直列チェーン**を持つ:

```
get_chat_thread(1)  →  get_current_user  →  profiles  →  saved_locations  →  chat_messages
```

`asyncio.gather`は最も遅いブランチの時間で全体が決まるため、**約1.8秒の大半
は、Phase B群の7つの並列読み取りではなく、Phase A1のこの1本の直列チェーンに
起因している可能性が高い**(構造的に確定。個々の秒数は次善の推定)。Supabase
(Auth API・PostgREST)への1回の呼び出しが仮に150〜400ms程度かかるとすると、
5段の直列チェーンで0.75〜2.0秒というレンジになり、観測された1.8秒とオーダー
として整合する。B群の7読み取り(並列)はこの1.8秒の枠内に収まって並走してい
るだけで、**それ自体が全体時間を押し上げてはいない**と考えられる。

### 3.2 残り約4.2秒(6秒 − 1.8秒)の内訳(推定)

生ログの全行タイムスタンプが得られていないため、以下はコード構造(呼び出し回
数・依存関係)から按分した**推定**であり、実測ではない。

| 区間 | 該当処理 | 推定所要時間 | 根拠 |
|---|---|---|---|
| 記憶コンテキスト構築 | `decompose_query`(B7)+検索RPC(embedding‖trgm→vector)+条件付き`rerank_candidates`(B10) | 0.5〜1.5秒 | nanoクラスの小型モデル想定+RPC2本 |
| chat.py側の前処理(2回目のchat_thread系+`get_profile_context`再取得) | 既存実装 | 0.3〜0.6秒 | 3〜4回の直列DB呼び出し |
| `classify_chat_intent` | 既存実装 | 0〜1.0秒 | ヒューリスティックで多くはスキップされるが、外れる場合は満額のLLM呼び出し |
| 本体応答生成(ツール呼び出し含む) | 既存実装 | 1.5〜3.0秒 | 単一区間として最大の可能性が高い。ツール呼び出しが挟まると更に伸びる |
| persona rewriteの初回トークンまで | 既存実装 | 0.3〜0.8秒 | ユーザーが最初の文字を見るのはこの後 |
| (以降、ユーザーには見えているがdoneイベント発火は遅延) `compare_semantic_entities`等 | 既存実装 | 0.4〜1.0秒 | 応答は見えているのでUX上の体感には影響しにくい |

**この按分が正しければ、全体約6秒のうち、Phase B群が直接寄与しているのは
「記憶コンテキスト構築」の一部(B7のdecompose_query+条件付きB10のrerank)の
み、おおよそ0.3〜0.8秒程度(全体の5〜15%程度)であり、既存実装(chat.py の意
図分類・本体応答生成、persona rewriteの二段構成)が全体の過半(50%以上)を
占めている可能性が高い**。ただし、これは2つの集計値からの逆算であり、正確な
比率は運用者側で生ログ(各行のミリ秒精度タイムスタンプ)を確認しない限り確定
できない。

### 3.3 構造上、確実に言えること(推定ではなく事実)

- Phase B群の7つの新規読み取りテーブルは**すべて既存の並列gatherに合流してお
  り、直列に積み重なってはいない**。
- ユーザーが最初の文字を見るまでに、**最低2回・最大4回の独立したLLM生成が直
  列に発生しうる**構造になっている(B7のdecompose_query、条件付きB10の
  rerank、chat.pyのclassify_chat_intent、chat.pyの本体生成、persona rewrite
  — このうち本体生成とpersona rewriteの2つは既存実装であり、必ず両方発生す
  る)。
- `get_profile_context()`(`auth/user`+`profiles`+`saved_locations`)は**キ
  ャッシュを一切持たず、1リクエスト中に最低2回、完全に重複した内容で呼ばれ
  ている**(Phase A1の`get_recent_messages_across_threads`から1回、chat.pyの
  `stream_chat_completion_ui`から1回)。運用者ログの「auth/user (2回)」はこ
  の重複そのものである。
- `chat_threads`テーブルも同様に、orchestrator層(`_ensure_chat_thread`)と
  chat.py層(`get_chat_thread`+`get_chat_thread_version`)の両方で、同じ
  `thread_id`に対して重複して読み取られている。

---

## 4. 運用者の仮説に対する結論

| 仮説 | 結論 | 根拠 |
|---|---|---|
| ①B6・B9・B14・B15・B16など複数のB群機能が独立してSupabase読み取りを行い、直列実行のため遅延が積み重なっている | **誤り(メカニズムの誤認)。読み取り自体は正しく並列化されている** | これら5機能の読み取りはすべて同一の`asyncio.gather`にまとめられており、直列ではなく並列実行されている(2章参照)。ただし、B7のdecompose_queryとB10のrerank_candidatesという**別の2機能**は、gatherの外で直列に新規LLM呼び出しを追加しており、これは実際に応答速度へ影響しうる(3.2節)。 |
| ②Phase A1(スレッド横断ログウィンドウ)・A2(プロンプトキャッシュ)など、Bより前の処理にまだ最適化されていない部分がある | **正しい(本調査で最も具体的に裏付けられた仮説)** | Phase A1の`get_recent_messages_across_threads`が、キャッシュなしの`get_profile_context()`を経由して`auth/user`+`profiles`+`saved_locations`の3回の直列読み取りを行っており、これがDB読み取り群(約1.8秒)の実質的なボトルネックである可能性が高い。加えてPhase A2のプロンプトキャッシュ順序の意図(`chat_prompts.py`の「安定した内容を前に、変動する内容を後ろに」という設計)が、B6・B14・B16が`_build_system_override()`に追加した文脈ブロックの並び順(検索結果由来の毎ターン変動するRAGコンテンツが先頭)によって、意図せず無効化されている可能性がある(5章で詳述)。 |
| ③`chat.py`の意図分類・本体応答生成・`rewrite_with_persona()`等、既存実装が支配的な遅延要因である可能性 | **正しい(構造的に確定)** | ユーザーが最初の文字を見るまでに、chat.pyの本体応答生成(ツール呼び出し込みで最大8回ループ)が完全に終わってから、persona_rewriter.pyの**別のLLM生成**が改めて開始される構造になっている。この2段構成そのものが既存実装(Phase A・Bいずれの対象でもない)であり、3.2節の推定では全体の過半を占める可能性が高い。 |
| ④上記のいずれか単独ではなく、複数が組み合わさっている | **正しい** | ②(既存実装A1の未最適化)と③(既存実装のchat.py+persona rewrite二段構成)が主要因であり、①のB群機能は(rerankの一部を除き)読み取り自体は正しく並列化されているため寄与は限定的。ただし①の一部(B7/B10の新規LLM呼び出し)とプロンプトキャッシュ順序への影響は実在する副次的要因である。 |

**総括**: 「B群が原因のはず」という運用者の初期仮説は、少なくとも**読み取りの
並列/直列という観点では誤り**だった。Phase Bが実際に追加した新規の直列LLM呼
び出し(B7・B10)は存在するが、それは全体の一部に過ぎない。応答速度低下の主
因は、**Phase Bより前から存在する既存実装**(`get_profile_context()`のキャッ
シュ欠如と重複呼び出し、chat.py本体生成→persona rewriteという二段の完全に別
のLLM生成が直列に連なる構造)にある可能性が高い。

---

## 5. 改善方針の提案(実装はしない、優先度順)

### 優先度1: `get_profile_context()`の重複排除・キャッシュ化

**現状**: 1リクエスト中に最低2回(Phase A1の`get_recent_messages_across_
threads`から、chat.pyの`stream_chat_completion_ui`から)、キャッシュなしで
`auth/user`+`profiles`+`saved_locations`を読み直している。

**方針案**: orchestrator/service.pyに既に存在する`_cache_get`/`_cache_set`
のTTLキャッシュパターン(B群の各`_cached_*`関数と同じ形)を`get_profile_
context()`自体、またはその呼び出し元に適用する。あるいは、Phase A1の
`get_recent_messages_across_threads`が既に取得している`user_id`をそのまま
chat.py側の呼び出しへ引数として伝搬させ、chat.py側での再取得自体を不要にす
る、という設計も考えられる。見積もり: この重複が3章の推定通りDB読み取り区間
の主要因なら、1リクエストあたり0.3〜1.0秒程度の短縮が見込める。

### 優先度2: 本体応答生成とpersona rewriteの二段LLM生成の統合、または部分ストリーミング化

**現状**: chat.pyの本体応答生成が完全に終わるまで、ユーザーには何も見えない
(tool_eventを除く)。その後さらにpersona_rewriter.pyが独立したLLM生成を行
い、その最初のdeltaでようやくユーザーに文字が見え始める。

**方針案**(実装はしない、方針のみ):
- (a) chat.pyの生成そのものにpersona.mdのトーンを反映させ、rewriteパスを
  廃止する(構成の大きな変更になるため、response_guard.pyが担っている「事実
  改変チェック」の役割をどこに移すかの再設計が必要)。
- (b) 現状の二段構成を維持しつつ、chat.py側のdeltaを「見えない下書き」とし
  てではなく、暫定表示として先にストリームし、persona rewrite完了後に差し替
  える、というUI側の工夫(バックエンドのみでは完結しない可能性がある)。
- (c) 最小の変更として、persona rewriteの`instructions`をあらかじめ固定文
  字列として構築せず、chat.py側の生成中に**先行してpersona_rewriterのAPI接
  続を確立しておく**(実際の生成開始はできないが、接続確立分のレイテンシは
  隠せる可能性がある)。

このうち(a)が最も大きな効果(二段のLLM生成を一段に減らせるため、3.2節の推
定で言えば1.5〜3.0秒 + 0.3〜0.8秒の合計のうち相当部分を削減できる可能性があ
る)が見込めるが、影響範囲が最も大きく、設計判断が必要なため、次のステップと
してまず影響範囲の洗い出しから始めることを推奨する。

### 優先度3: プロンプトキャッシュ順序の見直し(Phase A2の意図をB群の追加内容にも適用)

**現状**: `chat_prompts.py`は「安定した内容を先に、変動する内容を後ろに」と
いう意図的な順序を持つが、`schedule_agent_client.py::_build_system_
override()`が構築する`base_system`ブロックそのものは、**検索結果由来の毎タ
ーン変動するRAGコンテンツ(`user_profile_context`、B7〜B12の結果を含む)を
先頭に置き**、B6・B14・B16が追加した比較的安定した文脈(話題・判断傾向・目
標整合性)や固定文の`_BASE_SYSTEM_OVERRIDE`をその**後ろ**に置いている。この
ため、`base_system`ブロック内では実質的に毎ターンキャッシュ接頭辞が先頭付近
で途切れており、後続の(本来は安定している)ブロックまでキャッシュの恩恵を
受けられていない可能性がある。

**方針案**: `_build_system_override()`内の`parts`の並び順を、変動頻度の低い
ものから高いものへ(固定文→goal_alignment→topic→preference_patterns→
self_model→RAG結果である`user_profile_context`)に並べ替える。これは
`chat_prompts.py`が既に採用している設計方針をそのまま`_build_system_
override()`にも適用するだけであり、影響範囲は限定的(prompt構成の並び替えの
み、ロジック変更なし)。ただし、これは主にAPIコスト(キャッシュ課金割引)へ
の効果が大きく、レイテンシへの効果は副次的(数百ms程度)と考えられるため、
優先度は1・2より下とした。

### 優先度4: `_prepare_session_messages`内の直列チェーンの部分並列化

**現状**: `_ensure_chat_thread`(chat_threads読み取り)と`get_recent_
messages_across_threads`(内部でget_profile_context+chat_messages)が直列
に連なっている。

**方針案**: `get_chat_thread`(スレッド存在確認)と`get_recent_messages_
across_threads`(内部の`user_id`解決に必要な`get_profile_context`部分)は、
本来独立した読み取りであるため、`asyncio.gather`でまとめられる可能性があ
る。優先度1の対応(get_profile_contextのキャッシュ化)が実現すれば、この項
目の効果はキャッシュヒット時にはほぼ吸収されるため、優先度1と併せて検討する
のが効率的。

### 参考: 応答速度に直接影響しない、副次的に見つかった軽微な事項

調査中に、`orchestrator/service.py`の`run_orchestrator_chat`/`run_
orchestrator_chat_stream`双方で、`facts_ctx`(top-5事実)・`trends_ctx`
(top-3傾向)を`profile_context`に連結した直後(813〜827行目)、次の行
(829行目、`_build_memory_context()`の戻り値による完全な再代入)でその連結
結果が**丸ごと上書きされ、実質的に破棄されている**箇所を発見した。文字列連結
自体は軽量な処理であり応答速度への影響はごく僅かだが、意図した情報(top-5事
実・top-3傾向)がプロンプトに反映されていない可能性があるため、別途(本タス
クの範囲外として)確認することを推奨する。

> **追記(2026-07-05)**: この上書き問題は別タスクで修正済み。
> `docs/sigmaris/incident_facts_context_overwrite_fix.md`を参照。

---

## 6. 実測ログに基づく追加調査(2026-07-05)

前回(1〜5章)は実サーバーログにアクセスできない環境での**推定**だった。今
回、運用者が`journalctl -u sigmaris-backend -f -o short-precise`で取得した
実測ログ(`/chat`への1リクエスト、リクエスト受信13.913〜応答完了50.352、実
測合計**約36.4秒**)に基づき、推定を検証・訂正する。

### 6.1 「11.1秒の空白」(`24.857`〜`35.947`)の正体

**結論: ツール実行でもデッドロックでもなく、chat.pyの本体応答生成が実際に生
成・ストリーミングされている、正味の生成時間そのものである。** ログに何も出
力されないのは、この生成がユーザーには一切見えていない(!)状態で行われて
いるためであり、二重の意味で「見えない」時間になっている。

根拠は次の通り:

1. `httpx`のリクエストログ(`INFO [httpx] HTTP Request: ...`)は、
   **`stream=True`を指定した(SSEで結果を受け取る)OpenAI呼び出しでは、レス
   ポンスヘッダーを受信した時点(=接続確立時点)でログが出力され、本文
   (SSEの各チャンク)を読み切った時点では別途ログが出力されない**。一方、
   `stream=True`を指定しない呼び出し(`classify_chat_intent`・
   `compare_semantic_entities`)は、レスポンス本文を読み切った実際の完了時
   点でログが出力される。この違いは、ログ中の`23.960`
   (`classify_chat_intent`、非ストリーミング、直後に`chat stream routed`ログ
   が即座に続く=本当に完了している)と、`24.857`の直後に**何のログも続かず
   に11秒間沈黙する**という対比から特定した。
2. `chat.py`の`stream_chat_completion_ui()`の該当ループ
   (`for _ in range(8): stream = await client.responses.create(...,
   stream=True); async for event in stream: ...`)は、SSEの各`text-delta`
   イベントを内部変数`final_text`に蓄積するだけで、ここでは一切ログを出力し
   ない。ツール呼び出しが発生した場合のみ`"chat stream tool phase/execute/
   complete"`という`logger.info`が出るが、**今回のログにはこれらが一切登場
   しない**ため、この11.1秒間にツール(`read_home_context`等)は**呼ばれてい
   ない**と判断できる。意図分類の結果(`intent=general_chat`)とも整合する
   (雑談的な質問で、ツールを要しない応答だった)。
3. 11.1秒の沈黙の直後(`35.947`)に現れるのは、`auth/v1/user`→`profiles`→
   `saved_locations`→`chat_threads`→`PATCH chat_threads`(version更新)→
   `DELETE chat_messages`→`POST chat_messages`という一連の読み書きであり、
   これは`chat.py`の`_persist_chat_messages_safely()`→
   `replace_chat_messages()`(メッセージ永続化)の処理そのものと完全に一致す
   る。これは**本体応答生成のテキストが確定し、ループが`break`した後にしか
   到達しない処理**であるため、`35.947`の時点で本体応答生成は既に完了して
   いたことが確定する。

**すなわち、`24.857`(ストリーム接続確立)から`35.947`(次の処理に到達)まで
の約11.1秒は、chat.pyの本体応答生成が実際にトークンを生成し続けていた時間で
あり、「原因不明の空白」ではなく「本体生成そのものの実測所要時間」だった。**
これは前回調査で「本体応答生成: 1.5〜3.0秒」と見積もっていた区間の**実測値が
約4倍以上**だったことを意味する。運用者の当初仮説(ネットワークタイムアウ
ト待機・リトライ・デッドロック的待機)はいずれも**誤り**であり、単に「生成
に時間がかかっている実処理」だった。

ただし、この11.1秒間、**ユーザーには文字通り何も表示されていない**。
`orchestrator/service.py`の`run_orchestrator_chat_stream`は、chat.pyからの
`event.delta`を`schedule_text += event.delta`として蓄積するだけで、
`yield`しない(`event.tool_event`のみ即時中継)ため、この11.1秒はユーザー
体感としても完全な無反応区間である。

### 6.2 実測値に基づく全区間の内訳(前回推定との比較)

| 区間 | 前回の推定 | 今回の実測 | 対応する実装 |
|---|---|---|---|
| DB読み取り群(受信〜fact_items読込完了、`13.913`〜`16.616`) | 約1.8秒 | **約2.70秒** | 既存実装+B6/B9/B14/B15/B16並列読み取り |
| うち並列gather本体(`14.369`〜`15.190`) | (内訳なし) | 約0.82秒 | 既存実装+B6/B9/B14/B15/B16(並列、ボトルネックはPhase A1の`chat_messages`分岐) |
| うち`_cached_fact_items`(gather後・直列、`15.190`〜`16.024`) | (内訳なし) | 約0.83秒 | 既存実装+B17 |
| うち383件の`user_fact_items`受信後の処理(`16.024`〜`16.616`) | (見積もっていなかった) | 約0.59秒 | 既存実装(**新規発見**、6.5節参照) |
| audit insert | (内訳なし) | 約0.12秒 | 既存実装 |
| 記憶コンテキスト構築(`decompose_query`+検索RPC、`16.739`〜`20.380`) | 0.5〜1.5秒 | **約3.64秒** | Phase B7(2.07秒)+既存実装のembedding/vector検索(1.57秒) |
| HTTP hop+chat.py前処理(`20.380`〜`20.929`) | 0.3〜0.6秒 | 約0.55秒 | 既存実装(推定とほぼ一致) |
| `classify_chat_intent`(`20.929`〜`23.960`) | 0〜1.0秒 | **約3.03秒** | 既存実装(ヒューリスティック不一致でLLM呼び出しに委譲) |
| 本体応答生成 接続確立(`23.963`〜`24.857`) | (見積もっていなかった) | 約0.89秒 | 既存実装 |
| **本体応答生成 実処理(`24.857`〜`35.947`、旧「空白」)** | 1.5〜3.0秒 | **約11.09秒** | 既存実装(**ユーザーに一切見えない**) |
| メッセージ永続化(`35.947`〜`36.857`) | (見積もっていなかった) | 約0.91秒 | 既存実装(`get_profile_context`3回目、6.5節参照) |
| persona rewriteへの引き継ぎ(`36.857`〜`37.925`) | (見積もっていなかった) | 約1.07秒 | 既存実装 |
| **persona rewrite生成+semantic guard(`37.925`〜`47.928`)** | 0.3〜0.8秒(初回トークンまで) | **約10.00秒**(全体) | 既存実装(**ここはユーザーに見えている**) |
| guard失敗検知(`47.928`〜`47.931`) | (見積もっていなかった) | 約0.003秒 | 既存実装 |
| finish_invocation(`47.931`〜`48.349`) | (内訳なし) | 約0.42秒 | 既存実装 |
| `get_inquiry_question`(`48.349`〜`50.352`) | (見積もっていなかった) | **約2.00秒(2秒タイムアウトに酷似)** | Phase B3 |
| **合計** | 約6秒 | **約36.44秒** | — |

前回推定が大きく外れた理由: (1) 前回は生ログにアクセスできず、DB読み取り群
以外の全区間を「コード構造からの按分」で推定していたため、個々のLLM呼び出し
の実際のAPI応答時間(ネットワーク・モデル側の実処理時間)を反映できていなか
った。(2) 最大の要因である「本体応答生成」区間そのものを、ストリーミング呼
び出しの性質(ログが接続確立時点にしか出ない)を踏まえずに「1.5〜3.0秒」と
過小に見積もっていた。(3) persona rewriteについても同様に、ログの見た目上の
所要時間(接続確立から次のログまでの間隔)を「初回トークンまでの時間」と誤
認していた。

### 6.3 persona rewriteの実際の所要時間と、semantic guard failedの影響

`persona_rewriter.py`の`compare_semantic_entities()`は`stream=True`を指定
しない呼び出しであることをコードで確認した(`response_guard.py:121`)。した
がって`47.928`のログは**semantic guard呼び出し自体の実際の完了時刻**であ
り、`37.925`(persona rewriteストリームの接続確立)からこの間(約10.00秒)
には、①persona rewriteの実際のトークン生成・ストリーミング(大部分を占め
ると推定される)と、②その後に実行されるsemantic guardのLLM呼び出し、の両
方が含まれる。ログからは両者の内訳までは分離できないが、①がユーザーに実際
にストリーミングされる区間そのものであることは確実である(`rewrite_with_
persona_stream()`は`async for event in stream: ... yield
PersonaRewriteStreamEvent(delta=delta)`としてトークンを受け取り次第即座に
呼び出し元へ`yield`しており、orchestrator側もこれを即座に`yield
OrchestratorStreamEvent(delta=delta, ...)`としてユーザーへ中継しているた
め)。

**semantic guard failedの警告が処理時間の増加(リトライ)に繋がっていた
か**: **繋がっていない**。`rewrite_with_persona_stream()`のコードを確認す
ると、非ストリーミング版の`rewrite_with_persona()`(`for _ in range(2):
...`という2回までの再試行ループを持つ)とは異なり、**ストリーミング版には
再試行ループが存在しない**。semantic guardが失敗した場合、即座に
`yield PersonaRewriteStreamEvent(text=source, used_fallback=True,
guard_violations=..., done=True); return`として終了するのみで、再度LLMを呼
び直すことはない。ログでも、`47.931`(警告)から`48.349`(finish_invocation
のPATCH)までわずか0.418秒であり、追加のLLM呼び出しが挟まっていないことと整
合する。**したがって、この警告自体はレイテンシには影響していない。**

ただし、調査中に**レイテンシとは別の、実害の可能性がある副作用**を発見し
た: `orchestrator/service.py`のストリーミング処理は、`rewrite_with_persona_
stream()`から届く`delta`を、**semantic guardの判定結果を待たずに、届いた
その場でユーザーへ中継してしまっている**。`used_fallback=True`(=guard失
敗、事実改変の疑いあり)と判明するのは全delta配信後の`done`イベント時点で
あり、その時点で`response_text`という**内部変数**(監査ログ用)だけを
`source`(書き換え前の原文)に差し替えている。**つまり、ユーザーの画面には
既にguard判定NGとなった書き換え後のテキストがそのまま表示された状態であ
り、事後の差し替えは記録上の巻き戻しに過ぎず、画面表示は訂正されない**。今
回のケースでは「rewritten adds the person/name entity 「海星さん」」という
軽微な違反だったため実害は小さいと考えられるが、設計上、ストリーミング経路
では意図しない事実改変がユーザーに直接見えてしまう可能性がある。これは本タ
スクの調査範囲(レイテンシ)を超える発見のため、実装はせず、ここに記録する
のみに留める。

### 6.4 fire-and-forget処理がユーザー体感に影響していないかの確認結果

**確認不可**: 依頼文は`02:32:50.352`(invocation完了)以降、
`02:32:59.062`まで`memory_extractor`・`upsert_fact_item`の呼び出しが続くと
記載していたが、**今回実際に提供されたログは`02:32:50.352`(invocation完了
のログ行)で終了しており、それ以降の行は含まれていなかった**。そのため、
fire-and-forget処理の実際の所要時間や、後続リクエストへの影響有無を実測で
確認することはできなかった。

コード上の事実としては、`_extract_facts_bg`・`_cognitive_layer_bg`はいずれ
も`asyncio.create_task(...)`で起動されており、`run_orchestrator_chat_
stream`はこれらを`await`せずに直後の`yield OrchestratorStreamEvent(done=
True, ...)`へ進む(`orchestrator/service.py`1196-1209行目)。したがって**同
一リクエスト内でユーザーの応答がこれらの完了を待つことは構造上ありえない**
が、「次のリクエストが待たされないか」(例えば同一プロセスのイベントループ
が、fire-and-forgetタスクの実行によって次のリクエストの処理開始を遅延させ
ないか)は、生ログの続きなしには確認できない。この点は宿題として残る。次回
以降、`02:32:50`より後のログも含めて取得できれば、追加確認が可能である。

### 6.5 改善方針の優先順位の見直し

実測により、前回提案した4つの優先度のうち、**優先度2(二段LLM生成の統合)
が実測上ずば抜けて最大の効果を持つことが確定した**ため、優先順位を以下のよ
うに見直す。

| 新順位 | 内容 | 見直し理由 |
|---|---|---|
| **1**(旧2から昇格) | 本体応答生成とpersona rewriteの二段構成の統合・再設計 | 実測で、本体応答生成(ユーザーに見えない、約11.98秒: 接続確立0.89秒+実処理11.09秒)とpersona rewrite+guard(ユーザーに見える、約10.00秒)を合わせて**約22秒、全体36.4秒の60%以上**を占めることが確定した。特に前半の約12秒は**ユーザーに完全に見えない**時間であり、UX上最も改善効果が大きい。 |
| **2**(新規) | `classify_chat_intent`のヒューリスティック精度向上、または記憶コンテキスト構築との並列化 | 実測で3.03秒かかっており、前回の見積もり(0〜1.0秒)を大きく超えた。`classify_chat_intent`は`messages`/`attachment_facts`のみに依存し、`_build_memory_context()`(B7のdecompose_query等)や`get_profile_context`の結果に依存しないため、理論上は両者を並列実行できる可能性がある。ヒューリスティック(`heuristic_intent`)がなぜ今回不一致だったかの分析、または並列化のいずれかで、実質的な短縮が見込める。 |
| **3**(旧1、実測で影響が確認されたため据え置き) | `get_profile_context()`の重複排除・キャッシュ化 | 今回の実測で、`get_profile_context()`の内部呼び出し(`auth/user`+`profiles`+`saved_locations`)が**3回**(Phase A1の`get_recent_messages_across_threads`・chat.py本体・`replace_chat_messages`)発生していることが確認できた(前回の調査では2回と推定していたが、`replace_chat_messages()`内部でも呼ばれていることをコードで新たに確認した)。実測での追加コストは合計1秒未満程度と、優先度1・2ほど大きくはないが、実装の複雑さは低いため優先度3として維持する。 |
| **4**(新規) | `get_fact_items(active_only=True)`が`select=*`で`embedding`列(768次元ベクトル)を含む383件を取得している点の見直し | 実測ログで、`user_fact_items`のHTTPレスポンス受信(`16.024`)から件数ログ出力(`16.616`)まで約0.59秒かかっており、383件×768次元の埋め込みベクトルの転送・パースコストが疑われる。この関数の呼び出し目的(`build_facts_context`・`build_profile_context`等での利用)を確認すると`embedding`列は一切使用されていないため、Phase B5の`_DASHBOARD_SELECT`と同様に、必要な列のみを明示的に選択するSELECT列リストへの変更で、転送量を大きく削減できる可能性がある。 |
| **5**(旧3) | プロンプトキャッシュ順序の見直し | 実測データはこの項目に直接関係する追加証拠を提供しなかったため、順位を1つ下げるのみに留める。 |
| **6**(旧4) | `_prepare_session_messages`内の直列チェーンの部分並列化 | 実測(gather本体は約0.82秒で完了しており、前回懸念したほど大きなボトルネックではなかった)を踏まえ、優先度をさらに下げる。 |

**参考(新規発見、優先度付けはしないが記録)**: `get_inquiry_question`
(Phase B3)が2.003秒という、実装上のタイムアウト値(2.0秒)にほぼ一致する
時間で完了しており、**タイムアウトによって機能が実質的に失敗していた可能性
が高い**。これは応答完了までの時間には影響する(2秒間、後処理として待たさ
れる)ものの、ユーザーの主応答はその前に既に確定しているため、優先度表には
含めていない。ただし、Phase B3の機能が実運用で頻繁にタイムアウトしているの
であれば、別途Phase B3自体の見直し(タイムアウト値の調整、またはクエリの軽
量化)を検討する価値がある。

---

## 7. BA4後の追加調査(実測ログに基づく、2026-07-08)

**本章はコードの変更を一切行っていない。調査・報告のみ。** 本番の記憶データ
への書き込み・削除も一切行っていない(既存のコード・ドキュメント・運用者が
貼り付けたログの確認のみ)。

BA4(`docs/sigmaris/phase_ba4_report.md`、実務応答生成+人格変換の統合)完了
後、運用者が取得した実測ログでは1リクエストあたり約20.3秒(旧36.4秒から改
善)だった。一方で、(1)統合後の生成そのものが依然として重い区間(約8.3秒)
と、(2)前回調査で発見した「11秒の空白」と同種の性質を持つ新しい約5.3秒の空
白が残っていることが分かった。以下、運用者から提供された次のログ断片
(`02:31:26.669`受信〜`02:31:46.998`invocation完了、実測合計**約20.3秒**)
と、現行コード(`backend/app/services/chat.py`・`chat_routing.py`・
`orchestrator/service.py`・`orchestrator/schedule_agent_client.py`・
`orchestrator/response_guard.py`・`app/routes/agent.py`)を突き合わせて調査
した。

```
02:31:26.669  リクエスト受信(POST /api/orchestrator/chat/stream)
02:31:28.499  fact_items読込完了(493件)
02:31:31.567  検索RPC・embedding完了、chat stream start
02:31:31.833  chat stream context ready
02:31:40.135  1回目のPOST https://api.openai.com/v1/responses 完了
02:31:40.138  intent=general_chat と判定(routed)
02:31:40.957  2回目のPOST https://api.openai.com/v1/responses 完了
02:31:46.287  ★約5.3秒の空白★(次のログ: chat_threads取得)
02:31:46.466  chat_threads更新(PATCH, version=45)
02:31:46.587  chat_messages削除→再作成
02:31:46.998  invocation完了
```

### 7.1 「約8.3秒の生成」の正体: 実は統合生成ではなく`classify_chat_intent()`

**結論: `02:31:31.833`(context ready)から`02:31:40.135`(1回目のPOST完了)
までの約8.3秒は、BA4で統合された実務+人格の生成そのものではなく、その前段
にある意図分類(`chat_routing.py::classify_chat_intent()`)の、ヒューリステ
ィック不一致によるLLM呼び出し1回分である。** BA4が統合した生成呼び出し自体
は、この後の「2回目のPOST」以降(7.2節)である。

根拠は次の通り、コードの実行順序とタイムスタンプの整合性から特定した:

1. `chat.py::stream_chat_completion_ui()`のコード上の実行順序は、「chat
   stream context ready」ログ(746〜751行目)→`client =
   _require_openai_client()`(753行目、API呼び出しなし)→`route = await
   classify_chat_intent(...)`(754行目)→「chat stream routed」ログ(760
   行目)である。この2つのログの**間**に挟まっているのは`classify_chat_
   intent()`の呼び出し1回のみで、他のOpenAI呼び出しは一切ない。
2. `classify_chat_intent()`(`chat_routing.py`179〜261行目)は、まず
   `heuristic_intent()`で軽量なルールベース判定を試み、一致すればLLM呼び出
   しなしで即座に返す(この場合`source="heuristic"`)。**今回のログでは
   `source`の記載はないが、「1回目のPOST」が実際に観測されている以上、今回
   はヒューリスティックが一致せず、LLM呼び出し(243〜246行目、
   `client.responses.create(model=model, input=[...])`、**`stream`指定なし
   =非ストリーミング**)にフォールバックしたことが確定する。
3. 前回調査(6.1節)で確立した通り、`stream=True`を指定しないOpenAI呼び出
   しのhttpxログは、レスポンス本文を実際に読み切った**完了時点**で出力され
   る。`classify_chat_intent()`の呼び出しはまさにこの非ストリーミング呼び
   出しであるため、「1回目のPOST完了」(`40.135`)は、この呼び出しの**実際
   の所要時間そのもの**を表している。
4. 「1回目のPOST完了」から「intent=general_chat routed」ログまではわずか
   **3ミリ秒**(`40.135`→`40.138`)であり、これは`classify_chat_intent()`
   がOpenAI呼び出しの結果を受け取った直後に`json.loads()`で解釈し即座に
   returnし、呼び出し元がその3ミリ秒後にログを出す、という処理内容と整合
   する。もし「1回目のPOST」がBA4統合生成そのもの(`for _ in range(8):`
   ループ内の`client.responses.create(..., stream=True)`)だとすると、その
   呼び出しは`classify_chat_intent()`より**後**のコード位置にあるため、
   「routed」ログより先に完了することは構造上あり得ない。この一点だけでも
   「1回目のPOST」=`classify_chat_intent()`であることが確定する。

**`classify_chat_intent()`は`settings.openai_model`(`gpt-5.4-mini`、通常会
話・ルーティング用)を使用しており、BA4統合生成と同じモデル階層である
(過大なモデルを使っているわけではない)。** それでも約8.3秒かかっている
のは、直近8メッセージ分の文脈(`messages[-8:]`)+分類ルール一覧を含む非
ストリーミング呼び出しの、モデル自体の処理時間と考えられる。**この処理
は、BA4はもちろんBA1〜BA3のいずれによっても一切変更されておらず、Phase A
以前から存在する既存実装である。** 前回調査(3.2節)は「classify_chat_
intentは0〜1.0秒」と見積もり、6.2節の実測では「約3.03秒」だったが、今回は
約8.3秒であり、**この呼び出しの所要時間は実行のたびに大きくばらつく(かつ
全体的に増加傾向にある)** ことが分かる。加えて、この呼び出しは**非スト
リーミングであるため、ユーザーには実行中一切何も見えない**(`chat.py`の
`emit_status_delta`は`app/routes/agent.py`156行目付近の呼び出しで
`emit_status_delta=False`に固定されており、確認中メッセージも出ない)。
**BA4後の20.3秒のうち、最初に確定した約8.3秒がまるごとこの完全に無関係な
既存処理に費やされている**、というのが本節の結論である。

### 7.2 「約5.3秒の空白」の原因特定: BA4統合生成そのものの実処理時間(ただし今回はユーザーに見えている)

**結論: `02:31:40.957`(2回目のPOST完了)から`02:31:46.287`(次のログ)まで
の約5.3秒は、ツール呼び出しでもfact guardの実行時間でもなく、BA4で統合さ
れた実務+人格の生成(`chat.py`の`for _ in range(8):`ループ内、1回目の
`client.responses.create(..., stream=True)`)が実際にトークンを生成・スト
リーミングしている、正味の生成時間である。**

根拠:

1. `route`確定(`intent=general_chat`)後、`chat.py`は`router_instruction`・
   `system_prompt`の構築(文字列処理のみ、API呼び出しなし)を経て、879行目
   の`for _ in range(8):`ループに入り、881行目で「chat stream model
   request thread_id=... input_items=41 tools=[...]」をログ出力した直後
   (887行目)に`stream = await client.responses.create(model=settings.
   openai_model, instructions=system_prompt, input=response_input,
   tools=enabled_tools, previous_response_id=previous_response_id,
   stream=True)`を呼ぶ。**今度は`stream=True`が指定されている**ため、前回
   調査で確立した通り、httpxのログは接続確立(レスポンスヘッダー受信)時
   点で出力され、本文(SSEチャンク)を読み切った時点では別ログが出ない。
   よって「2回目のPOST完了」(`40.957`)は**この統合生成呼び出しの接続確立
   時点**であり、実際のトークン生成はここから始まる。
2. ログには`02:31:46.287`まで(tool phase/execute等のログを含め)一切出力
   がない。`chat.py`の`async for event in stream:`ループ(900〜920行目)
   は、`response.output_text.delta`イベントを受け取るたびに`final_text`へ
   蓄積し、SSEとして即座に`yield`する(913行目)のみで、**個々のdeltaを
   ログに出力するコードは存在しない**。ツール呼び出しが発生した場合のみ
   「chat stream tool phase/execute」ログ(922〜927・956〜960行目)が出る
   が、今回のログにはこれらが一切登場しない。したがって、この5.3秒間に
   ツール(`read_home_context`等)は呼ばれておらず、`intent=general_chat`
   (雑談的な質問でツール不要)という判定結果とも整合する。
3. ループを抜けた直後(1221〜1228行目、`orchestrator/service.py`)で呼ば
   れる`compare_response_to_tool_outputs()`(BA4で新設、事実確認guard)
   は、`response_guard.py`159〜186行目を確認したところ**同期関数(`async
   def`ですらない)で、正規表現/集合演算のみを行いLLM呼び出しを一切含まな
   い**。`tool_events`が空(今回はツール未使用)の場合は`source_text`が空
   文字列となり172〜173行目で即座にreturnする。このguardの実行時間はマイ
   クロ秒オーダーであり、5.3秒の空白には実質的に寄与していない。
4. `02:31:46.287`の直後に現れる「`chat_threads`取得」以降のログは、
   `_persist_chat_messages_safely()`→`replace_chat_messages()`(メッセージ
   永続化)の開始そのものであり、これは`async for event in stream:`ループ
   が`response.completed`イベントを受けて終了した後にしか到達しない処理で
   ある。したがって`46.287`時点で統合生成は既に完了していたことが確定する。

**旧「11秒の空白」との関係: 根本原因は同じ(ストリーミング呼び出しは接続確
立時にのみログが出る)だが、ユーザー体感としての性質は異なる。**

- 旧アーキテクチャ(BA4以前)では、`orchestrator/service.py`の`run_
  orchestrator_chat_stream()`は`chat.py`から届く`event.delta`を
  `schedule_text += event.delta`として**蓄積するだけでユーザーへyieldしな
  かった**(6.1節)。その後、完全に別のLLM生成である`rewrite_with_persona_
  stream()`が実務応答の全文確定後に初めて開始され、その最初のdeltaでよう
  やくユーザーに文字が見え始めていた。つまり旧「11秒の空白」は、**ログに
  も出ず、ユーザーにも一切見えない**、二重の意味での空白だった。
- BA4後の現行コードを確認したところ、`run_orchestrator_chat_stream()`
  (1188〜1213行目)は`call_schedule_agent_stream()`から届く`event.delta`
  を**受け取った直後に`OrchestratorStreamEvent(delta=...)`として即座に
  yield**している(1209〜1213行目、BA4報告書8章で言及された「delta即時中
  継」への回帰がそのまま現行コードに残っていることを確認)。さらにその手
  前、HTTP境界をまたぐ2箇所——`orchestrator/schedule_agent_client.py::
  call_schedule_agent_stream()`(289〜305行目、`aiter_lines()`で1行読むご
  とに即yield)と`app/routes/agent.py::agent_chat_stream()`の`_generate()`
  (191〜210行目、`upstream`から1チャンク受け取るごとに即yield)——も、いず
  れも受信した内容をバッファリングせず即座に中継する実装になっていること
  をコードで確認した。**したがって、今回の5.3秒間、ログには何も残らない
  ものの、ユーザーの画面上では(OpenAI側が実際にトークンを生成し次第)文
  字が随時ストリーミングされていたはずである。**
- ただし、この最後の一点(「ユーザー側で実際に体感として途切れなく文字が
  流れていたか」)は、**サーバーの構造化ログのみからは確認できない**。ロ
  グにはdelta単位のタイムスタンプが残らないため、OpenAI側が実際に最初の
  トークンを返すまでの時間(time-to-first-token)がこの5.3秒のうちどの程
  度を占め、そこから先どれだけ滑らかに(あるいは断続的に)後続トークンが
  届いたかは、今回のログからは判別できない。この点は断定を避け、「コード
  上はバッファリングされていないことが確認できた」という事実と、「実際の
  体感を保証するものではない」という限界を分けて報告する。

### 7.3 `fact_items`取得件数の増加が処理時間に与える影響

**今回の実測トレースにおいては、493件への増加が明確なボトルネックになって
いる証拠は見られなかった。** リクエスト受信(`26.669`)からfact_items読込
完了(`28.499`)までは約1.83秒であり、前回調査(383件)の`_cached_fact_
items`区間(gather後・直列、約0.83秒)と単純比較はできないものの(並列
gather区間の内訳が異なるため)、極端な悪化は見られない。これは`docs/
sigmaris/phase_ba2_report.md`で実施されたembedding列除外(`FACT_ITEM_
SELECT`、768次元ベクトルを転送・パース対象から除外)の効果によるものと考
えられる。

一方で、**設計として件数に比例して重くなる構造は変わっていない**ことを
コードで確認した:

- `orchestrator/service.py::_cached_fact_items()`(222〜238行目)は、
  `get_fact_items(jwt, active_only=True)`で**LIMIT指定なしに該当ユーザーの
  全アクティブfact行を毎回取得**する(300秒TTLキャッシュはあるが、キャッ
  シュミス時は常に全件取得)。
- `user_fact_data.py::build_facts_context()`は、取得した全件に対して
  `importance_score × confidence`でのソート(O(n log n))を行い、上位5件
  のみを使用する。ソート自体は軽量だが、**「上位5件のために毎回全件を取得
  してPython側でソートする」という設計自体が、記憶件数に比例してネット
  ワーク転送量・JSONパース時間を増加させ続ける**。
- Phase B-archロードマップのBA3(Memory Snapshot方式)は、B14・B16・B6・
  B9由来の集約情報(判断傾向・目標整合性・話題・関係性)を週次バッチで
  1つのSnapshotにまとめ、会話中はそれを読むだけにする設計を既に導入済み
  (`_cached_memory_snapshot()`、180〜198行目)である。**しかし`_cached_
  fact_items()`(生のfact行そのもの、facts_ctx用・決定/エピソード検出用)
  は、このBA3のSnapshot化の対象に含まれておらず、今回の調査でも変更され
  ていないことを確認した。**

**今後の懸念として記録**: 現状(493件)では顕著な問題は見られないが、記憶
件数がさらに大きく増加した場合(例えば数千件規模)、`_cached_fact_items()`
の全件取得・全件ソートは応答経路上の直列区間の一部であるため、いずれ無視
できない遅延要因になりうる。BA3のSnapshot方式の対象を、集約情報だけでなく
「facts_ctx用の上位N件」のような**事前計算済みの軽量版**にも広げることが、
将来の対応候補になる(実装はしない、方針のみ7.5節に記載)。

### 7.4 `chat_messages`全削除→全INSERT方式について

`02:31:46.466`(chat_threads更新PATCH、version=45)から`02:31:46.998`
(invocation完了)までは約0.532秒であり、このうち`02:31:46.587`
(chat_messages削除→再作成のログ)から完了までは約0.411秒だった。この
0.411秒には、`app_chat_data.py::replace_chat_messages()`内の
`rest_delete`(全削除)・`rest_insert`(全件再作成)に加えて、
`orchestrator/audit.py::finish_invocation()`の監査ログ更新も含まれている
(3つの処理の内訳はログの粒度からは分離できない)。

この全削除→全再作成方式自体(1ターンごとに、スレッド内の全メッセージを一
度DELETEしてから全件INSERTし直す)は、Phase A4以前から指摘されている既存
設計であり、BA4後の実測でも変わらず発生していることを確認した。今回の実測
では約0.4秒程度(監査ログ更新込み)であり、他の区間(8.3秒・5.3秒)と比較
すると相対的に小さい。ただし、これも(7.3節のfact_itemsと同様)**スレッド
内のメッセージ数に比例して重くなる設計**である点は変わっておらず、長期間
同一スレッドで会話を続けた場合の将来的な懸念として記録するに留める(実装
はしない)。

### 7.5 次に着手すべき改善の方針案(実装はしない、優先度順)

実測により、BA4完了後の約20.3秒のうち、**最大の要因は`classify_chat_
intent()`(約8.3秒、既存実装・BA1〜4未着手)であり、次いでBA4統合生成その
ものの正味処理時間(約5.3秒、ただしユーザーには見えている)** であること
が判明した。これを踏まえ、次の優先順位を提案する。

| 優先度 | 内容 | 根拠 |
|---|---|---|
| **1**(新規、最大の効果) | `classify_chat_intent()`の見直し | 実測で全体の約4割(8.3秒/20.3秒)を占め、かつユーザーには完全に不可視の非ストリーミング呼び出しである。前回調査(6.5節、旧優先度2)が既に指摘していたが、BA1〜4のいずれでも対応されていない。方針候補: (a) ヒューリスティック(`heuristic_intent()`)のカバレッジを広げ、LLM呼び出し自体を減らす、(b) LLM呼び出しが必要な場合でも、BA4統合生成と同じ`client.responses.create`呼び出しに`intent`判定を統合し(例えば統合生成の冒頭で軽く自己申告させる、またはtools選定をLLM任せにする等)、非ストリーミングの別呼び出しそのものを廃止する、(c) 記憶コンテキスト構築(`_build_memory_context`)と並列実行し、直列区間から外す。(c)は前回調査から実装難度が低いと見込まれていたが、依然未着手。 |
| **2** | BA4統合生成(`client.responses.create`)の入力量削減・レスポンス即応性向上 | Phase A1の`sigmaris_recent_message_window`(40件、`config.py`)+最新発話1件=`input_items=41`が毎回モデルに送られており、かつ`chat.py`は`previous_response_id`を毎回`None`にリセットしているため(Phase A1の設計、6.1節参照)、OpenAI側のプロンプトキャッシュ・レスポンスチェーンの恩恵を一切受けられず、41件分の文脈を**毎ターン最初から**処理させている。ウィンドウ件数の妥当性再検討、または`previous_response_id`チェーンを活かせる設計への変更(Phase A1の「スレッド横断」という目的とは両立しない可能性があり、要再設計)を検討する価値がある。 |
| **3** | `_cached_fact_items()`のSnapshot化(BA3の対象拡大) | 現状は顕著な問題ではないが(7.3節)、記憶件数に比例して重くなる設計上の負債であり、BA3の週次Snapshotの対象に「facts_ctx用の事前計算済み上位N件」を追加することで、会話中の全件取得・全件ソートを解消できる可能性がある。 |
| **4** | フロントエンドへの中間フィードバックの検討 | `classify_chat_intent()`実行中(最大8秒超)、ユーザーには何も表示されない(`emit_status_delta=False`)。優先度1の抜本対応が難しい場合の緩和策として、非ストリーミング呼び出し中であっても軽量な「考え中」表示を出す(バックエンドの`emit_status_delta`を状況に応じて`True`にする、等)ことで、体感速度を改善できる可能性がある。ただし本調査はバックエンド側コードの確認に留めており、フロントエンド側で独自のローディング表示が既にあるかどうかは未確認(範囲外)。 |

**優先度1が突出して効果が大きいと考えられる**理由: 8.3秒はBA1〜BA4のいず
れの対象にもなっていない、Phase A以前からの既存実装であり、かつBA4の本来
の狙い(二段階LLM生成の統合)が達成された結果、**相対的に最も目立つ残存要
因になった**。BA4着手前の36秒トレースでは、この呼び出しは他の巨大な要因
(11秒の空白+10秒のpersona rewrite)に埋もれて目立たなかったが、BA4完了
後の20.3秒トレースでは全体の4割を占める、最も明確に単離できるボトルネック
になっている。

---

## 8. `classify_chat_intent()`の実態調査(2026-07-08)

**本章はコードの変更を一切行っていない。調査・報告のみ。** 実モデルAPIへ
の新規呼び出しも行っていない(既存コードの精読と、既存ログの記述内容の確
認のみ)。7章で「BA4後の20.3秒のうち約4割(8.3秒)を占める、ユーザーには
一切見えない処理」と特定した`chat_routing.py::classify_chat_intent()`につ
いて、なぜこれほど時間がかかるのかを、コードに基づいて調査した。

### 8.1 判定ロジックの全体像

`heuristic_intent()`(`chat_routing.py`108〜176行目)は、次の順序で**5つの
特定インテント**(`schedule_import`・`calendar_write`・`mobility_plan`・
`event_lookup`、および明示的な操作タグ)のみを、キーワード一致で判定する:

1. `[shiftpilotai処理: ...]`という明示的な操作タグ(118〜127行目)
2. 添付ファイル・画像の有無(129〜130行目)→`schedule_import`
3. スプレッドシート系キーワード(132〜133行目)→`schedule_import`
4. カレンダー書き込みキーワード(`CALENDAR_WRITE_KEYWORDS`、135〜136行目)
   →`calendar_write`
5. カレンダー書き込みへの確認応答(直近文脈にカレンダー関連語があり、か
   つ「お願い」「はい」等の同意語がある場合、138〜145行目)→
   `calendar_write`
6. 移動・交通手段キーワード(147〜159行目)→`mobility_plan`
7. その他のカレンダー操作キーワード(161〜171行目)→`calendar_write`
8. 予定・日付キーワード(173〜174行目)→`event_lookup`
9. **上記のいずれにも一致しなければ`(None, None)`を返す**(176行目)

**重要な構造的事実: `heuristic_intent()`には`general_chat`を積極的に判定
する分岐が一つも存在しない。** `general_chat`は6種類の有効インテントの1つ
だが、ヒューリスティック側は他5種類のキーワードにマッチしなかった「残り
全部」としてしか`general_chat`を表現できない設計になっている。

`classify_chat_intent()`本体(179〜261行目)は、`heuristic_intent()`の戻
り値が`None`でなければ即座に返す(204〜209行目、`source="heuristic"`、
API呼び出しなし)。**`None`だった場合は必ずLLM呼び出しに進む**(242〜255
行目)。例外発生時のみ`general_chat`・`source="fallback"`にフォールバック
する(256〜261行目)。

### 8.2 今回の実測ケースがどちらの経路を通っていたか

**結論: LLM呼び出し経路(`source="llm"`)を通っていたと判断できる。** 根拠:

- 7章で確認した通り、`02:31:31.833`(context ready)から`02:31:40.135`
  (「1回目のPOST完了」)まで約8.3秒かかっている。ヒューリスティック経路
  はAPI呼び出しを一切行わない純粋な文字列比較であり、ミリ秒未満で完了す
  る。もしヒューリスティックが一致していれば、「chat stream routed」ログ
  は「chat stream context ready」ログの直後(数ミリ秒以内)に出力されてい
  たはずであり、8.3秒もの間隔が空くことはあり得ない。
- 同様に、例外発生時のフォールバック経路(256〜261行目)も、`try`ブロッ
  ク内で例外が送出された時点で即座に`except`に落ちるため、この経路も長時
  間の待機を伴わない。
- したがって、8.3秒という長い所要時間そのものが、「LLM呼び出しが行われ、
  実際に応答が返ってくるまで待った」ことの直接証拠であり、`intent=
  general_chat`という結果と合わせると、`source="llm"`だったと判断でき
  る(依頼文にある`intent=general_chat source=llm reason=...`という記述
  形式とも整合する)。ただし、本セッションでは`reason`欄の具体的な文言や
  今回のユーザー発言そのものの内容までは確認できていない(運用者側の生ロ
  グへの追加アクセスが必要)。

**なぜヒューリスティックで判定しきれなかったのか**: 8.1節で述べた通り、
`heuristic_intent()`は5つの特定インテント以外を検出する手段を持たない。
したがって、**今回の発言が「特に変わった性質だった」のではなく、単に
`CALENDAR_WRITE_KEYWORDS`・移動関連キーワード・「予定」等の日付キーワー
ドをどれも含まない、ごく普通の会話的な発言だった**、というのが最も自然な
説明である。これは例外的なケースではなく、**この判定ロジックの構造上、
キーワードに引っかからない発言は全てLLM呼び出しに進むという、設計そのも
のの帰結**である。

### 8.3 使用されているモデルの特定

`chat.py`753行目で`client = _require_openai_client()`(376〜379行目、
`AsyncOpenAI(api_key=settings.openai_api_key)`を**毎回新規作成**)が呼ば
れ、754行目で`classify_chat_intent(client=client, model=settings.openai_
model, ...)`が呼ばれている。すなわち:

- **`local_llm.py`の`get_llm_router()`/`TaskType`ルーティングシステムを
  一切経由していない。** B7のクエリ分解(`TaskType.QUERY_DECOMPOSITION`)
  やB14/B15/B16等の各種分類処理は、いずれも`get_llm_router().chat(TaskType.
  ...)`経由で呼ばれ、`local_llm.py::_openai_model_for_task()`
  (116〜138行目)によって`openai_nano_model`(`gpt-5.4-nano`、`config.
  py`のコメントでは「記憶抽出・要約・分類」用)にルーティングされる
  (該当TaskTypeは`_LOCAL_TASK_TYPES`にも含まれるため、`LOCAL_LLM_
  ENABLED=true`かつOllama到達可能であればローカルLLMにすら回りうる)。
  `classify_chat_intent()`はこのいずれの恩恵も受けない、**独立した直接
  呼び出し**になっている。
- 使用モデルは`settings.openai_model`(`gpt-5.4-mini`、`config.py`13行目
  のコメントでは「通常会話・ルーティング」用)であり、**BA4の統合生成本
  体と全く同じモデル階層**である。B7等の分類系処理が使う`gpt-5.4-nano`
  より重いモデルを、単純な6択分類に使っている状態である。
- `client.responses.create(model=model, input=[...])`(243〜246行目)呼
  び出しには、**`max_output_tokens`等の出力トークン上限が一切設定されて
  いない。** これは`local_llm.py`の`_OpenAIAdapter.chat()`(147〜165行
  目)が常に`max_completion_tokens`を設定している(呼び出し元は通常
  100〜800程度の値を渡す)のとは対照的である。GPT-5系モデルは内部で可変
  長の推論を行いうるため、出力上限を設けていないことが、今回観測された
  「3.03秒(前回調査6.2節の実測)→8.3秒(今回)」という大きな振れ幅の一
  因になっている可能性がある。**ただし、これは実際にAPIを追加で呼んで検
  証したものではなく、コード構造から導かれる仮説であることを明記する。**

**意図的な設計か、見落としか**: `chat_routing.py`のgit履歴を確認したとこ
ろ、この関数は`7efb9d4`(`initial project setup`)まで遡り、**`local_
llm.py`のTaskTypeベースのnano階層ルーティングが導入されるより前から存在
する、初期実装そのもの**であることが分かった。`chat.py`・`chat_
routing.py`のいずれにも、`gpt-5.4-mini`を意図的に選んだ理由を説明するコ
メントは存在しない。一方、`memory_search.py`177〜179行目には「Lazy
singleton so we don't reconstruct an AsyncOpenAI client on every call
(generate_embedding can now run on the hot path of every chat turn)」
という、**全く同種の「毎ターンのホットパスに乗った処理を、あとから最適化
する」という意識が既にこのコードベースに存在する**ことを示す先行例がある
(8.5節(c)で詳述)。以上を踏まえると、`classify_chat_intent()`が重いモデ
ル・上限なし・キャッシュなしのクライアントのまま残っているのは、**意図的
にモデルの正確性を優先した設計というより、TaskTypeシステム導入時に移行対
象から漏れた既存実装である可能性が高い**と判断する(ただし、運用者本人の
意図を直接確認したものではないため、断定はしない)。

### 8.4 LLM呼び出しに進む頻度の見積もり

本調査環境では`journalctl`等の実サーバーログに直接アクセスできないため、
実測での頻度算出は行えなかった。運用者側で確認可能であれば、次のような
集計コマンドで「chat stream routed」ログの`source`内訳を確認できる:

```bash
journalctl -u sigmaris-backend --since "-7 days" \
  | grep "chat stream routed" \
  | grep -oP 'source=\S+' \
  | sort | uniq -c
```

コードからの定性的評価: 8.1節で述べた通り、`heuristic_intent()`は
`general_chat`を積極的に検出する手段を持たず、**カレンダー・移動・予定
日付・添付ファイルのいずれのキーワードも含まない発言は、構造的に必ずLLM
呼び出しに進む**。Sigmarisは`persona.md`の設計上、単なるスケジュール管理
ツールではなく雑談・相談にも応じる「家庭支援AI」を志向しており、その種の
発言(相談・雑談・感想・当日の出来事の共有等)は上記いずれのキーワードに
も該当しないことが多いと考えられる。したがって、**LLM呼び出しへのフォー
ルバックは例外的なケースではなく、通常の会話ターンのかなりの割合(具体的
な比率は実測データなしには断定できない)で発生している可能性が高い**、
というのが本調査での定性的な結論である。

### 8.5 改善案の評価

#### (a) ルールベースの判定条件を拡充し、LLM呼び出しに進むケースを減らす

**効果には構造的な上限がある。** `general_chat`は「5つの特定インテント
のいずれでもない」という消去法でしか定義できない性質のインテントであり、
「雑談を検出するキーワード」を列挙する形の拡充には限界がある。より有望な
方向性は、**キーワードにマッチしなかった場合に無条件でLLM呼び出しに進む
現在のロジックを、「マッチしなければ`general_chat`として確定させ、LLM呼
び出しをスキップする」という形に反転させること**である。これは実装その
ものは非常に小さい(176行目の`return None, None`を`return "general_
chat", "heuristic-default"`に変える程度)が、**リスクを伴う**: 実際には
`mobility_plan`・`calendar_write`・`event_lookup`・`schedule_import`のい
ずれかに該当する発言が、たまたまキーワード集合(`CALENDAR_WRITE_
KEYWORDS`等)に含まれない言い回しをしていた場合、誤って`general_chat`に
分類され、`tool_names_for_intent()`(322〜371行目)が本来有効にすべき専
用ツール(例: `mobility_plan`の`plan_google_route`、`calendar_write`の
削除系ツール)が有効化されないまま応答が生成されてしまう。`general_chat`
用のツールセット(`read_home_context`・`search_app_events`・
`list_app_events`・`create_google_calendar_events`・`create_app_events`)
はある程度広いため実害は限定的な可能性もあるが、**8.4節の頻度データなし
にこのリスクの大きさを定量評価することはできない**。運用データを見た上
で、まずシャドウモード(LLM呼び出しは維持しつつ、ヒューリスティックが
`general_chat`をデフォルト推測していたらどうなっていたかをログに記録す
るだけに留める)で乖離率を観測してから本番投入するのが安全と考えられる。

#### (b) より軽量・高速なモデルに変更する

**実現可能性は高く、既存パターンへの合流という形で低リスクに実施でき
る。** `get_llm_router().chat(TaskType.ROUTING, ...)`(またはこの用途専
用の新規`TaskType`)経由に切り替えれば、次が同時に得られる:

- `openai_nano_model`(`gpt-5.4-nano`)への自動ルーティング
- `LOCAL_LLM_ENABLED=true`時のローカルOllamaへの自動フォールバック候補化
- `max_completion_tokens`上限の付与(現状は無制限、8.3節参照)
- `LLMRouter`が保持する再利用可能なクライアント(8.5節(c)のクライアント
  使い捨て問題も同時に解消される)

ただし、`local_llm.py`のアダプタは**Chat Completions API**
(`client.chat.completions.create`)を使う一方、`classify_chat_intent()`
は現在**Responses API**(`client.responses.create`)を使っている。入力の
組み立て(`input=[{"role":...,"content":[{"type":"input_text",...}]}]`
→`messages=[{"role":...,"content":...}]`)と出力の取り出し
(`response.output_text`→`response.choices[0].message.content`)を書き
換える、機械的だが実質的なリファクタリングが必要になる。また、6択分類
という判定精度が問われるタスクをnanoモデルに任せることで**誤判定率が上
がる可能性**があり、切り替え後はintentの分布・誤判定の兆候(例:
`calendar_write`が必要な場面で`general_chat`に落ちてツールが呼ばれない
等)を監視する必要がある。とはいえ、コードベース内には既に8種類の
`TaskType`がnano階層で分類タスクを問題なくこなしている実績があり
(B7のクエリ分解も含む)、**方向性としての妥当性は高い**と評価する。

#### (c) その他、調査の過程で見つかった改善案

1. **`max_output_tokens`の上限設定(モデル・APIは変更しない、最小変更)**:
   現在のResponses API呼び出しにトークン上限を追加するだけであれば、モデ
   ル階層やAPI形式を変えずに済む。8.3節で述べた「GPT-5系モデルの可変長推
   論が振れ幅の一因では」という仮説が正しければ、この一点だけでも所要時
   間の上限を大きく縮められる可能性がある。**変更範囲が最小(1〜2行)で、
   既存の分類精度・呼び出し経路を一切変えないため、(a)(b)より先に検証す
   る価値がある低リスクな候補**と評価する。
2. **`AsyncOpenAI`クライアントの使い捨てをやめる**: `chat.py::_require_
   openai_client()`(376〜379行目)は呼ばれるたびに新しい`AsyncOpenAI`イ
   ンスタンスを生成しており、`run_chat_completion()`(478行目)・
   `stream_chat_completion_ui()`(753行目)のいずれも、ターンごとに新規
   クライアントを作っている(1ターン内では`classify_chat_intent`と本体
   生成で同じインスタンスを使い回すが、ターンをまたいでは再利用されな
   い)。これは`orchestrator/schedule_agent_client.py`(モジュールレベル
   の`_http_client`シングルトン、明示的な`startup`/`shutdown`ライフサイ
   クルフック)、`local_llm.py`の`LLMRouter`シングルトン、
   `memory_search.py`177〜179行目(「Lazy singleton so we don't
   reconstruct an AsyncOpenAI client on every call」という、まさに同じ
   問題への既存の対処)と対照的であり、**このコードベースが既に認識・対
   処済みのアンチパターンが、`chat.py`だけ未対応のまま残っている**状態
   と言える。TCP/TLS接続の使い回しができないことは、OpenAI APIへの毎ター
   ンの接続確立コストとして、`classify_chat_intent()`・BA4統合生成本体
   の両方に影響しうる。**モデル・API・挙動を一切変えずに済む変更であ
   り、リスクは極めて低い。**
3. **`classify_chat_intent()`と記憶コンテキスト構築の並列化(前回調査6.5
   節、旧優先度2(c)で既に提案済み)は、見た目ほど単純ではない**ことを
   確認した。`orchestrator/service.py`は`_build_memory_context()`を
   **完全にawaitして完了させてから**、HTTP経由で`chat.py`
   (`classify_chat_intent`を含む)を呼び出す構造になっている。両者は同
   一プロセス内の別関数呼び出しではあるが、orchestrator→chat.pyの呼び出
   し境界(実HTTPホップ)を挟んでいるため、`asyncio.gather()`を1箇所に
   追加するだけでは並列化できない。真に並列化するには、intentの判定を
   orchestrator側の既存`asyncio.gather`(現在は`get_current_user`・
   `_cached_user_profile`等と並列)に合流させる、あるいは呼び出し境界そ
   のものを再設計する必要があり、**(a)(b)(c)-1、(c)-2より実装難度が高
   い**と評価する。

### 8.6 推奨する改善の優先順位(実装はしない、方針の提示のみ)

| 優先度 | 内容 | 根拠 |
|---|---|---|
| **1**(最優先・最小リスク) | (c)-1: `max_output_tokens`上限の設定 | モデル・API・分類ロジックを一切変えずに検証できる。8.3節の仮説(可変長推論が振れ幅の原因)が正しければ、これだけで大きな改善が見込める。まずこれを試し、効果を実測してから他の施策を検討するのが合理的。 |
| **2**(低リスク・独立して実施可能) | (c)-2: `AsyncOpenAI`クライアントのシングルトン化 | モデル・挙動を変えない、コードベース内に既に前例(`memory_search.py`)がある変更。`classify_chat_intent()`・BA4統合生成本体の両方に効く。 |
| **3**(中期・高価値だが実装コストあり) | (b): `local_llm.py`のTaskTypeシステムへの移行(nano階層化) | 優先度1・2を実施してもなお遅い場合の本命。nano階層・トークン上限・クライアント再利用が一括で手に入るが、Responses API→Chat Completions APIへの書き換えと、切り替え後の誤判定率モニタリングが必要。 |
| **4**(データdrivenで判断) | (a): ヒューリスティックの「マッチしなければgeneral_chat確定」への反転 | 8.4節の頻度データ(LLM呼び出しに進む実際の割合)と、優先度1〜3を実施した後の残りの所要時間を見た上で、必要性とリスクを再評価する。シャドウモードでの乖離観測を先に行うことを推奨する。 |
| **5**(長期・アーキテクチャ変更を伴う) | 8.5節(c)-3: orchestrator/chat.py境界の再設計による並列化 | 効果は見込めるが、他の4項目と比べて影響範囲・実装難度が大きい。優先度1〜4で十分な改善が得られない場合に検討する。 |

**優先度1・2を推奨する理由**: いずれもモデルの分類精度や既存のツール選
択ロジックに一切影響を与えず、既存コードのごく一部(トークン上限の追
加、クライアントのシングルトン化)を直すだけで済む。8.3節で見つかった
「上限なしのResponses API呼び出し」「毎ターン使い捨てのAsyncOpenAIクラ
イアント」は、いずれも`classify_chat_intent()`固有の問題ではなく、それ
ぞれ独立に検証・修正できる**低リスクな既存の見落とし**であり、(a)(b)の
ような判定ロジック自体の変更に先立って試す価値が高いと判断する。

---

## 9. `classify_chat_intent()`の軽量化実施(トークン上限+クライアント再利用、2026-07-08)

対象ブランチ: `fix-classify-intent-lightweight`(mainからfork)

8章の優先度1・2(いずれも「モデルの分類精度・既存ツール選択ロジックを一
切変えない」低リスク施策)を実施した。優先度3(nano-tier移行、API方式の
変更を伴う)は本タスクの範囲外とし、別タスクとして後日実施する。

### 9.1 設定したトークン上限の値とその根拠

`chat_routing.py::classify_chat_intent()`のLLM呼び出し(243〜246行目→変更
後は243〜263行目付近)に、`max_output_tokens=800`を追加した。

**根拠**: 実際のログに出力された`reason`欄の具体的な文字数は、本セッショ
ンで確認できる生ログには含まれていなかった(8.4節で既に明記した制約と同
じ)ため、実測値からの逆算はできなかった。代わりに、次の2点から値を決定
した:

1. **出力形状からの見積もり**: `classify_chat_intent()`が要求する出力は
   `{"intent": "...", "reason": "..."}`という、6種類のenumから選んだ
   `intent`と短い正当化理由の2フィールドのみのフラットなJSONである。この
   コードベース内で同種の「短いJSON分類結果」を返すLLM呼び出しの既存の
   トークン予算を参考にした: `active_inquiry.py`の確認質問生成は
   `max_tokens=100`〜`200`、`abstention_feedback.py`の反応分類は
   `max_tokens=100`。一方、`goal_alignment.py`の目標整合性フラグ抽出
   (`_ANALYZE_PROMPT`、複数フラグを含みうる、より複雑な多フィールド
   JSON)は`max_tokens=800`であり、**このコードベースで単一のJSON分類/抽
   出呼び出しに設定されている既存の最大値**である。
2. **GPT-5系(推論対応)モデル特有のリスクへの配慮**: `classify_chat_
   intent()`が使う`settings.openai_model`(`gpt-5.4-mini`)は推論能力を
   持つモデル階層であり、Responses APIの`max_output_tokens`は(OpenAIの
   公開仕様上)可視出力だけでなく、モデル内部の推論トークンも合算した上
   限として扱われる。8.3節で立てた仮説(上限なしが所要時間の振れ幅の一
   因)を検証したいのはもちろんだが、**上限を厳しくしすぎると、モデルが
   推論の途中でトークン予算を使い切り、有効なJSONを一度も出力できないま
   ま打ち切られるリスクがある**。この場合、既存コードの`intent not in
   VALID_INTENTS`判定(249〜250行目)によって`general_chat`に自動的に
   フォールバックされるため**クラッシュはしない**が、これは要件3(「意図
   分類の判定結果・精度が、変更前後で変わらないこと」)に反する**サイレ
   ントな精度劣化**になりうる。

以上の理由から、**最も引き締めた値(例: 100〜300程度)ではなく、このコー
ドベースの既存の最大値である800を、そのまま流用する形で採用した**。実測
での妥当性検証(この上限で本当に十分か、逆に短すぎないか)は、本タスクの
制約(新規のAPIキー・サーバーアクセスを取得しない)により実施できていな
い。**本番投入後、`intent`が想定外に`general_chat`へ偏っていないか(=上限
超過によるフォールバックが多発していないか)を監視することを、9.5節の申
し送り事項として明記する。**

### 9.2 クライアント再利用の実装詳細

`chat.py::_require_openai_client()`(旧376〜379行目)を、`memory_
search.py`の`_openai_embed_client`(177〜179行目、239行目付近)と**全く
同じ設計**で書き換えた:

- モジュールレベルに`_openai_client: AsyncOpenAI | None = None`を新設
  (`memory_search.py`の`_openai_embed_client`と対になる命名)。
- `_require_openai_client()`内で`global _openai_client`を宣言し、
  `None`のときのみ`AsyncOpenAI(api_key=settings.openai_api_key)`を生成し
  てキャッシュ、以降は同じインスタンスを返す。
- `memory_search.py`の該当コメント(「Lazy singleton so we don't
  reconstruct an AsyncOpenAI client on every call (generate_embedding can
  now run on the hot path of every chat turn)」)と同じ理由付けを、
  `_require_openai_client()`側のコメントにも明記した(`classify_chat_
  intent()`・`run_chat_completion()`・`stream_chat_completion_ui()`のい
  ずれも毎ターンのホットパスに乗っている、という文脈を揃えた)。

**`memory_search.py`のパターンをそのまま踏襲し、明示的な`startup`/
`shutdown`ライフサイクルフックは追加しなかった**。判断根拠: `memory_
search.py`の`_openai_embed_client`自体、`supabase_rest.py`・
`schedule_agent_client.py`のhttpxクライアントとは異なり、明示的な
`aclose()`の呼び出し箇所がコードベース内のどこにも存在しないことを確認
した(`grep`で確認済み)。`AsyncOpenAI`クライアントはプロセス終了まで生存
させても実害がない(既存の`_openai_embed_client`が既に同じ運用を先例と
してこなしている)ため、今回新設した`_openai_client`も同じ「プロセス寿命
まで生存する遅延シングルトン」という、既存パターンとの一貫性を優先した
設計にした。

`run_chat_completion()`(492行目)・`stream_chat_completion_ui()`(767行
目、いずれも変更後のファイルでの行番号)は、いずれも`_require_openai_
client()`の呼び出し方自体は変更していない(呼び出し元のコードは1行も変
えていない)。関数の中身だけを差し替えたため、**呼び出し側から見た挙動
(1ターン内で`classify_chat_intent`と本体生成が同じインスタンスを共有す
る)は従来通り維持しつつ、ターンをまた
いだ再利用が新たに可能になった**。

### 9.3 テスト結果

`backend/tests/`には未コミット(既存方針に合わせスクラッチテストとして
実行のみ)。実モデルAPI・実Supabase接続へのアクセスは行っていない。

- トークン上限を追加した`client.responses.create()`呼び出しに、実際に
  `max_output_tokens=800`が渡されていることの直接確認(1件)
- 現実的な長さの`reason`文字列(150文字程度の英文)を含むモックレスポン
  スが、上限追加後も正しくパースされ、`reason`の内容が欠落しないことの
  確認(1件、要件3の直接検証)
- ヒューリスティックでは判定しきれない発言(カレンダー関連キーワードを
  含まない言い回し)を経由したLLM分類が、`calendar_write`のような
  `general_chat`以外のintentも引き続き正しく返せることの確認(1件)
- ヒューリスティック経路(意図的にキーワードを含む発言)が、今回の変更
  後も**LLM呼び出しを一切行わずに**即座に判定できることの回帰確認(1
  件、トークン上限追加が誤ってヒューリスティック分岐に影響していないこ
  との確認)
- 上限超過等でLLMが空/不正なJSONしか返せなかった場合でも、既存の
  `intent not in VALID_INTENTS`フォールバックにより例外を投げず
  `general_chat`に安全に縮退することの確認(1件、9.1節で述べたリスクに
  対する既存の安全弁が変更後も機能することの確認)
- `AsyncOpenAI`クライアントが、`_require_openai_client()`を複数回呼んで
  も1回しか生成されず、常に同一インスタンスが返されることの確認(1件、
  要件2の直接検証)
- `OPENAI_API_KEY`未設定時は、クライアントをキャッシュせずに例外を送出
  することの確認(1件、失敗時に壊れたクライアントがキャッシュに残り続
  けないことの確認)

```
16 passed (既存の回帰テスト一式、backend/tests/)
7 passed  (本タスクの新規テスト、トークン上限3件+クライアント再利用2件
           +安全弁1件+ヒューリスティック回帰1件)
= 23 passed
```

### 9.4 レイテンシへの影響(見積もり、実測は未実施)

指示書の制約(新規のAPIキー・サーバーアクセスを取得しない)に従い、実モ
デルAPIでの前後比較測定は行っていない。以下はコードから導かれる見積もり
であることを明記する。

- **トークン上限**: 8.3節の仮説(GPT-5系モデルの可変長推論が、3.03秒→
  8.3秒という振れ幅の一因)が正しければ、`max_output_tokens=800`という
  上限は、**上限なしの状態で発生しうる極端な外れ値(青天井の推論)を頭打
  ちにする**効果が期待できる。ただし800という値自体は、8.3節で観測され
  た所要時間(3〜8秒)を大きく下回るほど厳しい上限ではなく、**典型的な
  応答時間そのものを大きく短縮するというより、まれに発生する極端に長い
  ケースを抑える**方向の効果を狙ったものである。実際にどの程度の分布に
  なるかは、本番投入後の実測(9.5節)でのみ確定できる。
- **クライアント再利用**: 修正前は、`stream_chat_completion_ui()`(また
  は`run_chat_completion()`)が呼ばれるたびに新しい`AsyncOpenAI`インス
  タンス(=新しいhttpx接続プール)が生成されていたため、そのターンで最
  初にOpenAIへ発行するリクエスト(今回の実測ケースでは`classify_chat_
  intent()`のLLM呼び出しがこれに該当する)は、常にゼロから新しいTCP/TLS
  接続を確立する必要があった。修正後は、同一プロセス内であればターンを
  またいで同じ接続プールが再利用されるため、**2ターン目以降は、直前の
  接続がkeep-aliveで生きていれば新規ハンドシェイクを省略できる**可能性
  がある。TLS接続確立にかかる時間は一般に対向サーバーとのネットワーク
  条件に強く依存し(数十ミリ秒〜数百ミリ秒程度が典型的なレンジと考えら
  れる)、本番環境での正確な値はネットワーク経路依存のため、コードから
  の見積もりだけでは断定できない。

**次回、本番サーバーで実測ログを取得する際は、`classify_chat_intent()`
区間の所要時間の分布(平均・最大値)が、8章時点(3.03秒〜8.3秒)と比べ
てどう変化したかを重点的に確認することを推奨する。**

### 9.5 次のタスク(nano-tier移行)に向けた申し送り事項

- **`intent`分布の監視**: 9.1節で述べた通り、`max_output_tokens=800`が
  実際に十分な値かどうかは実測でしか確認できない。本番投入後、
  `general_chat`への分類が不自然に増えていないか(=フォールバックの多
  発を示唆する)を、`chat stream routed`ログの`intent`/`source`内訳
  (8.4節に記載した集計コマンドを流用可能)で確認することを推奨する。
- **nano-tier移行(優先度3)は本タスクで一切着手していない**: 8.5節(b)
  で評価した通り、`local_llm.py`の`get_llm_router()`/`TaskType`システム
  への移行は、Responses API(`client.responses.create`+
  `response.output_text`)からChat Completions API
  (`client.chat.completions.create`+
  `response.choices[0].message.content`)への入出力の組み替えを伴う、本
  タスクより大きい変更である。今回`max_output_tokens`を追加したことで、
  移行時に「nano-tierでのトークン予算をいくらにすべきか」の判断材料(現
  行の800という値、およびその根拠)が既に用意された状態になっている。
- **今回追加した`_openai_client`シングルトンは、nano-tier移行後は不要に
  なる可能性がある**: `classify_chat_intent()`がnano-tier
  (`get_llm_router()`経由)に移行すれば、その呼び出しは`local_llm.py`
  の`LLMRouter`(既に独自のクライアント再利用機構を持つ)を使うようにな
  り、`chat.py`の`_openai_client`はBA4統合生成本体(`run_chat_
  completion`・`stream_chat_completion_ui`の本体`client.responses.
  create`呼び出し)専用になる。この場合でも`_openai_client`自体は引き続
  き必要(本体生成はResponses APIのまま、nano-tier移行の対象外であるた
  め)だが、「1つの関数が2つの別々の目的でOpenAIクライアントを使ってい
  る」という状態が「1つの関数が1つの目的のためだけに使う」状態に単純化
  される、という点は移行時に意識するとよい。
- **8.5節(a)(ヒューリスティックの反転)・(c)-3(orchestrator/chat.py境
  界の再設計)は、いずれも本タスクの範囲外のまま**。優先度3(nano-tier
  移行)の効果を実測してから、必要性を再評価するという8章の推奨順序は
  変わっていない。

---

## 10. 意図分類軽量化後の再実測・追加調査(2026-07-08)

**本章はコードの変更を一切行っていない。調査・報告のみ。** 実モデルAPI
への新規呼び出しは行っていない(既存コードの精読と、運用者提供のログの
突き合わせのみ)。9章の対応(`max_output_tokens`上限+クライアント再利
用)後、実サーバーで再実測したところ、全体は約20.3秒→約18.3秒(約2.0秒
短縮)、`classify_chat_intent()`自体は約8.3秒→約3.7秒に改善していた一方
で、短縮幅が意図分類の改善幅より小さいという不整合が報告された。以下、
提供されたログ断片(`06:41:38.354`受信〜`06:41:56.639`invocation完了、
実測合計**約18.285秒**)と現行コード(`local_llm.py`・`multihop_
search.py`・`memory_search.py`・`chat.py`・`chat_routing.py`・
`orchestrator/service.py`)を突き合わせて調査した。

### 10.1 Ollama疎通確認の挙動

**結論: 矛盾ではない。互いに独立した2つのキャッシュが、異なる基準で疎通
判定を行っているために生じている見た目上のズレである。**

- `local_llm.py::LocalLLMClient.is_available()`(78〜113行目)は、**単な
  る`/api/tags`応答の有無だけでなく、設定されたチャット用モデル
  (`self._model` = `settings.ollama_model`)が実際にインストール済みモ
  デル一覧に含まれているか**まで確認する(96〜111行目)。同メソッドの
  docstring(79〜91行目)には、まさに今回のログと同じ状況を指して書か
  れたと思われる説明が既に残っている:「A bare "does /api/tags respond"
  check used to be enough to mark Ollama "available"... but a server can
  have Ollama running with only an embedding model installed (e.g.
  nomic-embed-text) and no chat model at all. That looked "available"
  here...」。すなわち、`06:41:40.495`の「Ollama not reachable」という警
  告は、**Ollamaサーバー自体に接続できなかったという意味ではなく、
  「接続はできたが、設定されているチャット用モデルが見つからなかった」
  ことを指している可能性が最も高い**。ログメッセージの文言
  (`"Ollama not reachable at %s"`、199〜202行目)自体がこの区別を表現
  できておらず、誤解を招きやすい表現になっている点は事実として指摘して
  おく。
- 一方、`memory_search.py::_probe_ollama_embed_available()`
  (196〜210行目)は、**`response.is_success`のみを見る、単純な到達性
  チェック**であり、モデルの種類は一切確認しない。Ollamaサーバー自体は
  生きており、埋め込み用モデルも動いていると考えられるため、こちらの
  プローブは素直に成功し、その後の`Ollama embeddings 呼び出し成功`
  (`06:41:44.337`)にもつながっている。
- **したがって「矛盾」ではなく、「到達性だけを見る判定」と「特定モデル
  の有無まで見る、より厳格な判定」という、2つの異なる基準による、正し
  い(設計通りの)結果の相違である。** 実際にOllamaサーバー上でチャット
  用モデル(`settings.ollama_model`の設定値)がインストールされているか
  どうかは、本セッションからは確認できない(サーバーアクセスが必要)。
  運用者側で`ollama list`等により確認することを推奨する。

**なぜ1リクエスト中に2回呼ばれているように見えるのか**: `local_llm.py`
の`LLMRouter._local_available`(180行目、195〜202行目)は「Probe
availability once per **router lifetime**」という明示的なコメント付き
で、**プロセス起動後の最初の1回だけ**プローブし、以降は結果をキャッシュ
し続ける設計になっている(`get_llm_router()`はモジュールレベルのシング
ルトンであるため、これは実質「プロセスの寿命全体で1回」を意味する)。
`memory_search.py::_ollama_embed_available`(175行目)も同様に、**モジ
ュールレベルの変数として、プロセス起動後の最初の1回だけ**プローブする
設計になっている。**すなわち、両方とも既にキャッシュされており、「キャ
ッシュされていないために毎リクエスト呼ばれている」わけではない。** 2つ
の独立したキャッシュが、今回たまたま同じリクエスト内で**それぞれ初めて**
呼び出されたために2回のGETが観測された、というのが最も自然な説明であ
る。9章の改修(`classify_chat_intent`のトークン上限・クライアント再利
用)はバックエンドプロセスの再デプロイ(再起動)を伴うため、**再起動後
最初にこれらのコードパスを通ったリクエストが今回の実測ケースだった可能
性が高い**(9.1節後半で述べる通り、両プローブが「プロセスの寿命全体で1
回」の設計であることと整合する)。この場合、次回以降のリクエストではど
ちらのプローブも再実行されない(=無駄な待機は今回限りで、今後は発生し
ない)。**ただし、キャッシュされた結果自体(Ollamaのチャット用モデルが
利用不可)は再起動しない限り変わらないため、プローブ自体のコストとは別
に、「ローカル対象のTaskType呼び出しがOpenAIにフォールバックし続ける」
というコストは、プロセスが生きている限り毎ターン発生し続ける**(10.4節
で詳述)。

**疎通確認自体の所要時間**: ログの秒未満の解像度で見る限り、2回のGET
`/api/tags`はいずれも、直後のログ(1回目は`WARNING`、2回目は次の処理の
ログ)とほぼ同時刻に記録されており、**プローブ自体が数秒単位の待機を生
んでいる形跡はない**。プローブ自体は軽量であり、時間を消費しているの
は、プローブの「結果」に基づいて後続のLLM呼び出しがどこにルーティング
されるか、という部分である(10.4節)。

### 10.2 「context ready→1回目のresponses完了」約3.7秒の内訳

**結論: この区間は8章で特定したのと同じ`classify_chat_intent()`のLLM呼
び出しであり、他の処理(本体応答生成の最初の呼び出し等)ではない。9章
のトークン上限追加は、実際に所要時間を短縮させている(8.3秒→3.7秒)。**

根拠:

- URLパスで区別できる: `06:41:48.478`のログは`https://api.openai.com/
  v1/responses`(Responses API)へのPOSTであり、`chat_routing.py::
  classify_chat_intent()`(243〜266行目、変更後)が使うのと同じエンドポ
  イントである。これに対し、`06:41:42.958`の「1回目」と見えるログは
  `https://api.openai.com/v1/chat/completions`(Chat Completions API)
  への別のPOSTであり、URLが異なる。**運用者の依頼文が「1回目のPOST」
  と呼んでいるものは、実際にはこの2つの異なるAPI呼び出しの、さらに後に
  ある`/v1/responses`への呼び出しを指しており、`classify_chat_intent()`
  であることに変わりはない**(8章で確立した「`stream`未指定=完了時点
  でログが出る」という判定基準とも一致する)。
- `chat.py`のコード順序上、「chat stream context ready」ログ(現在の行
  番号で確認済み)の直後は、`client = _require_openai_client()`
  (9.2節でシングルトン化済み、以降はオブジェクト生成コストなし)→
  `route = await classify_chat_intent(...)`であり、この間に他のOpenAI
  呼び出しは挟まらない。よって「context ready」から「1回目の
  `/v1/responses`完了」までの約3.7秒は、実質的に`classify_chat_
  intent()`の呼び出し1回分の所要時間そのものである。
- **依頼文にある「`classify_chat_intent()`自体は...今回は約0.05秒とほぼ
  消えている」という理解は、ログの読み方に起因する誤解であると判断す
  る。** `06:41:48.526`(routed)と`06:41:48.478`(1回目の`/v1/
  responses`完了)の差である0.05秒は、**OpenAI呼び出しが完了してから、
  `json.loads()`で結果を解釈し戻り値を組み立てて`chat.py`側がログを出
  すまでのローカル処理時間**であり、`classify_chat_intent()`のLLM呼び
  出し自体の所要時間ではない。呼び出し自体の所要時間は、「context
  ready」から「1回目の`/v1/responses`完了」までの**約3.7秒**である
  (8章での判定方法——非ストリーミング呼び出しは完了時点でログが出る、
  かつ直後のアプリケーションログとの間隔が数ミリ秒であること——と全く
  同じ基準で判定した結果であり、8章の8.3秒のケースと対称的に解釈でき
  る)。
- 9章の改修の影響評価: **`max_output_tokens=800`の追加、および
  `AsyncOpenAI`クライアントのシングルトン化は、いずれもこの呼び出しに
  直接影響する変更である。** 8.3秒→3.7秒という結果は、8章で立てた仮説
  (上限なしの推論が振れ幅の一因)と整合する方向の変化であり、**改善そ
  のものは実際に起きている**と判断できる。ただし、3.7秒は依然として短
  くはなく、`max_output_tokens=800`という上限のもとでもなお数秒かかっ
  ていることから、**トークン数の制限だけでは根本的な高速化には至ってお
  らず、8章で評価した優先度3(nano-tier移行)の効果検証が改めて重要に
  なる**ことが今回のデータからも裏付けられた。

### 10.3 「6.4秒の空白」の原因特定

**結論: 前回(7.2節)の「約5.3秒の空白」と同一の現象(BA4統合生成本体の
ストリーミング実処理時間、ログに出ないだけでユーザーには配信されてい
る)であり、構造的な変化ではなく、別のユーザー発言に対する生成の自然な
所要時間差と考えられる。**

- `06:41:49.378`(2回目の`/v1/responses`接続確立)から`06:41:55.788`
  (次のログ)までの間、ツール呼び出し関連のログ(`chat stream tool
  phase`/`execute`)が一切登場しないことをログから確認した(依頼文の
  ログ断片にも含まれていない)。7章で確立した通り、この区間は
  `chat.py`の`async for event in stream:`ループ(BA4統合生成本体)が実
  際にトークンを生成・ストリーミングしている時間であり、個々のdeltaは
  ログに出力されない。7.2節で確認した通り、`orchestrator/service.py`
  は受信したdeltaを即座にユーザーへ中継する実装のままであり(今回の
  9章の改修はこの経路に一切触れていない)、この点に変化はない。
- 前回(約5.330秒)と今回(約6.410秒)の差(+約1.08秒)について: この
  区間の所要時間は、その回のユーザー発言・応答内容によって生成トーク
  ン数が変わるため、**本質的にターンごとに変動する量**である。9章の変
  更(`classify_chat_intent`のトークン上限・クライアント再利用)は、
  この区間のコード(`chat.py`の生成ループ本体、`response_guard.py`の
  `compare_response_to_tool_outputs()`、`orchestrator/service.py`の
  delta中継部分)を一切変更していないため、**コード上の変化に起因する
  ものではないと判断する**。約1秒程度の差は、異なる発言に対する応答長
  の違いやAPI応答時間の自然なばらつきの範囲内と考えるのが妥当である。
  ただし、これは消去法による判断であり、実際の応答内容(トークン数)を
  直接比較したものではないことを明記する。

### 10.4 全体としての整合性評価: なぜ2秒しか縮まなかったか

**結論: 「意図分類がほぼ消えた」という前提そのものが誤り(10.2節)であ
り、実際には8.3秒→3.7秒という約4.6秒の改善が起きている。この改善分
は、(a)`decompose_query()`のOllamaフォールバックコスト(約2.5秒、9章
の改修とは無関係に元々存在していた可能性が高い)と、(b)本体生成スト
リーミング時間の自然な変動(約1.1秒)によって大きく相殺され、結果とし
て約2.0秒の純減にとどまった。**

区間ごとの前回(20.3秒)・今回(18.3秒)を比較すると、次のようにきれい
に説明がつく:

| 区間 | 前回(7章) | 今回(本章) | 差分 |
|---|---|---|---|
| A: リクエスト受信→context ready(記憶コンテキスト構築含む) | 5.164秒 | 6.434秒 | **+1.270秒** |
| B: context ready→1回目`/v1/responses`完了(`classify_chat_intent`) | 8.302秒 | 3.690秒 | **-4.612秒** |
| C: routed→2回目`/v1/responses`接続確立 | 0.822秒 | 0.900秒 | +0.078秒 |
| D: 2回目接続確立→次ログ(本体生成ストリーミング) | 5.330秒 | 6.410秒 | **+1.080秒** |
| E: 次ログ→invocation完了(永続化+監査) | 0.711秒 | 0.851秒 | +0.140秒 |
| **合計** | **20.329秒** | **18.285秒** | **-2.044秒** |

区間ごとの差分を単純合計すると`+1.270 -4.612 +0.078 +1.080 +0.140 =
-2.044`となり、**実測の合計差(20.329秒→18.285秒 = -2.044秒)と完全に
一致する**(端数の丸め誤差を除く)。この一致自体が、上記の区間分割が実
態を正しく捉えていることの裏付けになっていると考える。

区間Aの+1.270秒について: 10.1節で確認した通り、`decompose_query()`
(B7、`_build_memory_context()`の一部としてrequest受信〜context ready
の間に実行される)が、Ollamaのチャット用モデル不在によりOpenAIへフォー
ルバックし、約2.463秒の非ストリーミングChat Completions API呼び出しに
なっていた。**ただし、この`decompose_query()`のフォールバックコスト
自体は、9章の改修や今回の再起動によって新たに発生したものではなく、
前回(20.3秒)の測定時点でも既に発生していた可能性が高い**と判断する。
根拠: 本ドキュメント6.2節(旧36秒トレースの実測)の時点で、既に
「decompose_query(B7): 2.07秒」という、今回とほぼ同オーダーの数値が記
録されている。`decompose_query()`・`multihop_search.py`・
`local_llm.py`は、BA1〜BA4・9章のいずれの変更でも一切触れられていない
ため、**この所要時間はこれまでの複数回の測定を通じて一貫して存在して
いた、構造的に安定したコストである可能性が高い**。7章の調査ではこの区
間([context ready以前])を詳細に分解していなかったため、区間Aの内訳
としてこれまで可視化されていなかっただけで、**区間Aが+1.270秒「悪化」
したというより、以前から存在していたコストが今回初めて数値として捕捉
された、と解釈するのがより正確**と考えられる(この解釈自体は、区間A
の詳細な内訳を前回測定時に取得していないため断定はできない)。

区間Dの+1.080秒について: 10.3節の通り、コード上の変更が一切ないた
め、応答内容によるトークン数の違い等、ターンごとの自然な変動と判断す
る。

**「Ollama疎通確認の無駄な待機が意図分類の短縮効果を相殺しているか」**
という依頼文の問いに対する回答: **疎通確認そのもの(GETリクエスト)は
無駄な待機を生んでいない(10.1節、プローブ自体はミリ秒オーダー)。相
殺しているのは、疎通確認の「結果」(Ollamaのチャット用モデルが使えな
い)によって`decompose_query()`がOpenAIへフォールバックしていること
(約2.5秒)であり、これは意図分類の改善(約4.6秒)の半分以上を打ち消
す規模である。** ただし上述の通り、このフォールバックコスト自体は9章
の改修とは独立に以前から存在していた可能性が高く、「意図分類の改善を
Ollama疎通確認が新たに相殺した」というより、「意図分類という1つの大き
な要因が改善された結果、元々あった別の要因(decompose_queryのOllama
フォールバック)の存在がより目立つようになった」という理解の方が実態
に近いと考える。

### 10.5 次に着手すべき改善案(実装はしない、方針の提示のみ)

| 優先度 | 内容 | 根拠 |
|---|---|---|
| **1**(新規・最大の潜在効果) | Ollamaのチャット用モデル設定の確認・修正(コード変更ではなくインフラ/設定の確認) | `settings.ollama_model`に設定されているモデルが、実際にOllamaサーバーにインストールされているかを`ollama list`等で確認する。もし未インストールであればインストールする、あるいは`settings.ollama_model`の値を実際にインストール済みのモデルに合わせる。これが解消されれば、`decompose_query()`(B7)だけでなく、`_LOCAL_TASK_TYPES`に含まれる全てのTaskType(`MEMORY_EXTRACTION`・`DECISION_DETECTION`・`EPISODE_DETECTION`・`TOPIC_DETECTION`・`MEMORY_RERANK`・`ABSTENTION_REACTION_DETECTION`等、B2・B7・B10・B14・B15等の多数のfire-and-forget処理を含む)が、OpenAIフォールバックでなくローカル推論を使えるようになり、応答経路上・バックグラウンド処理の両方で広範な速度改善が見込める、**本調査で見つかった中で最も波及効果が大きい候補**。実装(コード変更)を伴わない、設定・運用上の対応である点にも留意。 |
| **2**(8章から継続) | `classify_chat_intent()`のnano-tier移行(8.5節(b)、9章では未着手) | `max_output_tokens`上限だけでは3.7秒までしか縮まらなかった。優先度1(Ollama復旧)が実現すれば、nano-tier移行時にローカル推論の恩恵も受けられるため、両者を組み合わせる効果が見込める。 |
| **3**(新規) | `decompose_query()`自体の所要時間の妥当性調査 | OpenAIフォールバック時で約2.0〜2.5秒(nano-tier、`max_tokens=300`)かかっており、`classify_chat_intent()`と同種の「軽量なはずの分類処理が数秒かかる」問題が疑われる。優先度1で根本原因(Ollama不在)が解消されればこの調査の必要性は下がるが、解消されない場合は同様の切り分け調査を行う価値がある。 |
| **4**(新規・可用性の懸念) | `_local_available`/`_ollama_embed_available`の再プローブ機構の検討 | 両キャッシュは「プロセス起動後1回だけ」判定し、以降は再起動までその結果を使い続ける設計になっている。Ollamaが一時的に落ちていたタイミングでプロセスが起動した場合、その後Ollamaが復旧しても、プロセスを再起動するまでローカル推論には一切戻らない。TTL付き再プローブ(orchestrator側の他のキャッシュが採用している300秒TTLパターンの流用等)を検討する余地がある。 |

**優先度1を最上位とする理由**: 8章・9章は`classify_chat_intent()`という
単一の呼び出しの改善に取り組んだが、今回の調査で「Ollamaのチャット用モ
デルが利用できていない」ことが判明し、これは`classify_chat_intent()`
以外の、**このコードベース全体に広がる多数のB群バックグラウンド処理・
`decompose_query()`にも影響する、より上流の問題**であることが分かっ
た。この1点を解消することが、個別の呼び出しを1つずつ最適化していくよ
り、投資対効果の観点で優れていると判断する。

---

## Related Documents

- `docs/sigmaris/phase_a1_report.md`(スレッド横断ログウィンドウの設計意図)
- `docs/sigmaris/phase_b7_report.md`(応答経路への新規LLM呼び出しの最初の事
  例、レイテンシに関する既存の見積もり)
- `docs/sigmaris/phase_b10_report.md`(応答経路への2つ目の新規LLM呼び出し)
- `docs/sigmaris/phase_b_summary.md`(応答経路上のLLM呼び出し数がB7・B10の2
  つのみである、という従来の認識。本調査により、既存実装側の直列LLM呼び出し
  ・二段生成構造の方がより大きい可能性があるという追加の知見が得られた)
- `docs/sigmaris/incident_facts_context_overwrite_fix.md`(5章末尾で触れた
  facts_ctx/trends_ctx上書き問題の修正報告)
- `docs/sigmaris/phase_b3_report.md`(`get_inquiry_question`のタイムアウト
  設計)
- `docs/sigmaris/phase_b_arch_roadmap.md`(BA1〜BA5のサブフェーズ構成、7章
  の調査対象)
- `docs/sigmaris/phase_ba1_report.md`・`docs/sigmaris/phase_ba2_report.md`
  (BA1・BA2の実施報告)
- `docs/sigmaris/phase_ba4_report.md`(応答生成の統合、7章が実測で検証した
  対象そのもの)
