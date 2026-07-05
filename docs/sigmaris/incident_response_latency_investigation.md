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

---

## Related Documents

- `docs/sigmaris/phase_a1_report.md`(スレッド横断ログウィンドウの設計意図)
- `docs/sigmaris/phase_b7_report.md`(応答経路への新規LLM呼び出しの最初の事
  例、レイテンシに関する既存の見積もり)
- `docs/sigmaris/phase_b10_report.md`(応答経路への2つ目の新規LLM呼び出し)
- `docs/sigmaris/phase_b_summary.md`(応答経路上のLLM呼び出し数がB7・B10の2
  つのみである、という従来の認識。本調査により、既存実装側の直列LLM呼び出し
  ・二段生成構造の方がより大きい可能性があるという追加の知見が得られた)
