# Sigmaris Live Live-1 実施報告: イベント発行の基盤設計、調査

## はじめに・本タスクの性質

**本タスクは調査・設計のみを目的とし、本番コードへの変更は一切行っていない。** 検証のため、リポジトリ外(セッションのスクラッチパッド)に、独立した実験用スクリプト1本を作成し実行したのみで、`backend/app/`配下の既存ファイルは1行も変更していない(3章末に実験内容を記載)。

着手前に、依頼書が指定した以下を確認した。

- `docs/sigmaris/phase_ba4_report.md`(応答生成の統合。1回目のschedule-agent生成をそのまま最終応答として採用する方式へ移行し、旧`rewrite_with_persona_stream()`によるpersona書き換えを廃止した経緯)
- `docs/sigmaris/incident_response_latency_investigation.md`(1〜11章。特に7章「BA4後の追加調査」・8章「`classify_chat_intent()`の実態調査」・11章「nano-tier移行」)
- `docs/sigmaris/phase_g_report.md`(G-1〜G-5、Trigger Detection・Evidence Structuring・Self-Critique・Citation Audit・Grounding Health)

**重要な前提の確認**: `incident_response_latency_investigation.md`は2026-07-08時点の調査であり、その後G群・R群・S群・Vis群・Safety群・H群の実装を経て、現在の`orchestrator/service.py`・`chat.py`のコード行数・処理内容は、同報告書の記述からかなり増えている(例えば`run_orchestrator_chat_stream()`は同報告書が参照する行番号[972-1213行目]から、現在は[1473-1761行目]まで移動・拡張している)。本調査は、**同報告書を出発点としつつ、実際に現在のコードを直接読み直して**、以下の整理を行った。同報告書との差分(B9のentity_hint、B11の確信度、B12の圧縮、Temporal Layerの日記検索、G-1〜G-2の統合等)は、2章で明示する。

---

## 1. 既存の処理フローの整理結果

### 1.1 全体の時系列(現在のコードに基づく、正確な整理)

`POST /api/orchestrator/chat/stream`(`routes/orchestrator.py`)→ `run_orchestrator_chat_stream()`(`orchestrator/service.py:1473-1761`)が、実際の処理の起点である。

```
① request_started
   run_orchestrator_chat_stream() 開始(service.py:1482, started_at計測開始)

② [並列gather、7本](service.py:1493-1502)
   auth・user_profile・self_model・threshold_adjustment・dissent_boldness_adjustment・
   active_trends・_prepare_session_messages()(A1、内部に最大5段の直列DB読み取り連鎖)
   → fact_items・memory_snapshot(user_id判明後、並列、service.py:1508-1511)
   → start_invocation()(監査ログ書き込み、service.py:1538-1556)

③ memory_search_started / memory_search_finished
   _build_memory_context()(service.py:741-873)の中核部分:
   - build_entity_hint()(B9、LLM呼び出しなし、文字列処理のみ、service.py:807)
   - search_with_decomposition()(B7、multihop_search.py:228-)
       - decompose_query()(B7、★条件付きLLM呼び出し★、質問が複合的と判定された場合のみ)
       - search_relevant_memories()(A5/B1、embedding生成‖trgm検索を並列実行後、vector検索RPC)
       - rerank_candidates()(B10、★条件付きLLM呼び出し★、候補数が上限超の場合のみ)
   - classify_confidence_tier()(B11、LLM呼び出しなし、既存シグナルの分類のみ、service.py:825-830)
   - compress_memories_if_needed()(B12、ルールベース、LLM呼び出しなし、service.py:843-845)
   - [条件付き] diary date-range検索(Temporal Layer、日付+日記トリガー語を含む発言のみ、service.py:862-870)

④ [HTTPホップ] call_schedule_agent_stream() → POST /api/agent/chat/stream
   → stream_chat_completion_ui()(chat.py:965-)

⑤ intent_classification_started / intent_classification_finished
   classify_chat_intent()(chat.py:1003-1006、chat_routing.py:180-)
   - heuristic_intent()(ルールベース、LLM呼び出しなし)が一致すれば即座に返す
   - 一致しない場合のみ、TaskType.CHAT_INTENT_CLASSIFICATION経由のLLM呼び出し
     (★11章でnano階層へ移行済み、ただし依然として最大級の所要時間になりうる箇所★)
   - 同時にdetect_search_need()(G-1、ルールベース)がsearch_signalを算出

⑥ [条件付き] evidence_search_started / evidence_search_finished
   _gather_evidence_and_context()(chat.py:76-95、G-2)
   - route["search"]["needs_search"]がtrueの場合のみ実行
   - gather_search_evidence()(evidence_search.py:263-287):
       run_web_search()(1回のLLM呼び出し、web_searchツール付き)
       → structure_evidence()(nano階層、1回のLLM呼び出し、TaskType.EVIDENCE_STRUCTURING)

⑦ response_generation_started / response_generation_finished
   chat.py:1130-の`for _ in range(8):`ループ
   - client.responses.create(..., stream=True) — 本体応答生成(実際にstreamingで
     ユーザーに届く、最初のLLM生成)
   - ツール呼び出しが発生した場合、都度execute_tool()を直列await(最大8回ループ)
   - [条件付き] tool_call_started / tool_call_finished(ツールごと)

⑧ compare_response_to_tool_outputs()(BA4、response_guard.py:159-、同期関数、
   正規表現・集合演算のみ、LLM呼び出しなし、マイクロ秒オーダー)

⑨ finish_invocation()(監査ログ書き込み、service.py:1676-1689)

⑩ [条件付き、既定offf] pending_inquiry surfacing(B3、service.py:1696-1700、
   settings.sigmaris_surface_inquiry_questions=Falseが既定のため通常は発火しない)

⑪ request_finished
   OrchestratorStreamEvent(done=True, ...) がyieldされる(service.py:1753-1760)
   ここまでが「ユーザーが応答を受け取り終える」までの経路

⑫ [fire-and-forget、応答は既に返却済み、以降はユーザー体感に一切影響しない]
   _extract_facts_bg() / _maybe_stash_future_inquiry() / _cognitive_layer_bg() /
   _mark_events_mentioned_bg()(service.py:1703-1751)
   + chat.py側のself_critique/citation_audit(G-3/G-4、chat.py:120-155、
     run_verification_checks()、advisory-onlyでdoneイベント後に実行)
```

### 1.2 依頼書の例示イベントリストとの、重要な相違点

依頼書が例示した`intent_classification_started/finished → memory_search_started/finished → belief_update_started/finished → response_generation_started/finished`という順序は、**実際のコードの時系列とは異なる**。実際には、**記憶検索(③)が意図分類(⑤)より先に発生する**——`_build_memory_context()`は`orchestrator/service.py`内で、HTTPホップ(④)によって`chat.py`へ処理が渡る前に完了している。`classify_chat_intent()`は、その後`chat.py`に処理が渡ってから初めて呼ばれる。

これは正確な調査結果として明記する必要があると判断した(依頼書「推測ではなく、実際のコードを確認した上で、調査すること」への直接対応)。以降の設計は、依頼書の例を「参考にした一般的なイベント名の語彙」として尊重しつつ、**実際の時系列順**でイベントリストを組み立てる。

また、`belief_update`(信念更新)に直接対応する、応答生成前の単独処理は、現在のコードには存在しなかった。最も近いのはB11の`classify_confidence_tier()`(確信度の分類、LLM呼び出しなし)だが、これは「記憶検索の結果を評価する」処理であり、独立した段階というよりmemory_searchの一部として扱うのが実態に即している(2.2節)。「信念そのものの更新」に相当する処理(`user_fact_items`への書き込み等)は、応答生成**後**の`_cognitive_layer_bg()`(fire-and-forget、⑫)の中で行われており、応答が返り終わった後の話である。

---

## 2. 設計したイベントのリストと、含めるべきデータ

### 2.1 トップレベルイベント一覧(発生順)

| # | イベント名 | 発生源(現在のコード) | 条件 |
|---|---|---|---|
| 1 | `request_started` | `service.py:1482` | 毎ターン必須 |
| 2 | `context_prepared_finished` | `service.py:1511`直後 | 毎ターン必須(開始は`request_started`と実質同時のため、`_finished`のみ発行) |
| 3 | `memory_search_started` | `service.py:808`直前 | 毎ターン必須 |
| 4 | `memory_search_finished` | `service.py:846`直後 | 毎ターン必須 |
| 5 | `intent_classification_started` | `chat.py:1003`直前 | 毎ターン必須 |
| 6 | `intent_classification_finished` | `chat.py:1006`直後 | 毎ターン必須 |
| 7 | `evidence_search_started` | `chat.py:94`直前 | `needs_search=true`の場合のみ |
| 8 | `evidence_search_finished` | `chat.py:95`直後 | 同上 |
| 9 | `response_generation_started` | `chat.py:1138`直前(ループ1周目のみ) | 毎ターン必須 |
| 10 | `tool_call_started` / `tool_call_finished` | `chat.py:1207`/実行完了後 | ツール呼び出しが発生した場合のみ、ツールごと |
| 11 | `response_generation_finished` | `chat.py`のループを抜けた直後 | 毎ターン必須 |
| 12 | `request_finished` | `service.py:1753`直前 | 毎ターン必須 |

**「なぜ`context_prepared_started`を設けないか」の判断根拠**: `request_started`と、並列gatherの開始は、コード上ほぼ同時(同一関数内の連続する数行)であり、2つのイベントを分けても情報量が増えない。依頼書の例が`request_started`を独立させていた設計意図(リクエスト全体の開始を明示する)を尊重しつつ、無意味なイベント数の増加は避けた。

**「なぜdiary検索(Temporal Layer)を独立イベントにしないか」の判断根拠**: 発生頻度が低く(日付+日記トリガー語を含む発言のみ)、`memory_search`という同じ「記憶に関する検索」という意味的まとまりの中にある処理である。独立イベントにするより、`memory_search_finished`のペイロードに`diary_search_triggered: bool`を含める方が、イベント数を無闇に増やさずに実態を反映できると判断した。

### 2.2 各イベントに含めるべきデータ

**共通フィールド(全イベント)**:
```json
{
  "event": "memory_search_finished",
  "invocation_id": "uuid",
  "timestamp": "2026-07-18T12:34:56.789Z",
  "elapsed_ms": 1234
}
```
`invocation_id`は、既存の`orchestrator/audit.py::start_invocation()`が発行するIDをそのまま流用する(新しいID体系を作らない——依頼書にはない判断だが、既存の監査ログとの突き合わせを容易にするための追加の設計判断)。

**ステージ別の追加フィールド(要約情報のみ、4章のプライバシー方針に従う)**:

| イベント | 追加フィールド | 除外する情報 |
|---|---|---|
| `context_prepared_finished` | `is_new_thread: bool` | fact_itemsの中身・profile内容 |
| `memory_search_started` | (なし) | — |
| `memory_search_finished` | `result_count: int`, `was_decomposed: bool`(B7), `confidence_tier: "confident"\|"hedged"\|"abstain"`(B11), `diary_search_triggered: bool` | 記憶の本文・類似度スコアの生値・fact_itemsの内容 |
| `intent_classification_started` | (なし) | — |
| `intent_classification_finished` | `intent: string`(6値のいずれか), `source: "heuristic"\|"llm"`, `needs_search: bool` | ユーザーの発言内容そのもの、分類理由の自由文(`reason`フィールドは除外——ヒューリスティック理由・LLM理由のいずれも、発言の引用を含みうるため) |
| `evidence_search_started` | (なし) | — |
| `evidence_search_finished` | `citation_count: int` | 検索クエリ文字列、citation本文・URL(5章で詳述) |
| `response_generation_started` | (なし) | — |
| `tool_call_started` | `tool_name: string` | 引数(位置情報・カレンダー内容等を含みうる) |
| `tool_call_finished` | `tool_name: string`, `ok: bool` | 実行結果の内容 |
| `response_generation_finished` | `response_length: int`(文字数のみ) | 応答本文そのもの(既にstreamingで別経路にて本人には見えているが、外部観測用イベントには含めない、4章で詳述) |
| `request_finished` | `total_elapsed_ms: int`, `guard_violations_count: int` | — |

---

## 3. 安全な組み込み方の検討(配信方式の選択を含む)

### 3.1 fire-and-forgetパターンの適用設計

依頼書の必須方針「イベント発行自体が失敗しても、本来の処理には一切影響しない」を、既存の`asyncio.create_task(...)`パターン(このコードベース全体で既に11箇所以上で確立済み——`orchestrator/service.py`内だけでも`_extract_facts_bg`・`_cognitive_layer_bg`・`_mark_events_mentioned_bg`・`_maybe_stash_future_inquiry`等)を、そのまま踏襲する。

提案する呼び出し方(擬似コード、本番への組み込みは行っていない):
```python
def emit_live_event(event_type: str, invocation_id: str, **fields) -> None:
    """fire-and-forgetのイベント発行。失敗しても呼び出し元には一切伝播しない。"""
    asyncio.create_task(
        _publish_live_event(event_type, invocation_id, fields),
        name=f"live_event:{event_type}:{invocation_id}",
    )

async def _publish_live_event(event_type, invocation_id, fields) -> None:
    try:
        await live_event_bus.publish({...})
    except Exception:
        logger.exception("sigmaris_live: event publish failed type=%s", event_type)
```
`_publish_live_event()`自身が、既存の`_extract_facts_bg()`等と同じく、内部で例外を握りつぶす(try/exceptで自己完結させる)設計にする。これは3.2節の実験で確認した通り、fire-and-forgetタスクが例外を送出すると「Task exception was never retrieved」という警告がログに残る(呼び出し元には伝播しないが、ログが汚れる)ため、既存のコードベースの全fire-and-forgetヘルパーが徹底している「タスク内部で自己完結して例外を処理する」という規律を、本設計でも踏襲する必要があると判断した。

`emit_live_event()`自体は同期関数とし、呼び出し元(`_build_memory_context()`や`classify_chat_intent()`の呼び出し箇所)から`await`せずに呼べる形にする——これにより、呼び出し箇所への変更は「1行追加」に近い最小の侵襲で済む。

### 3.2 実験による検証: fire-and-forgetのオーバーヘッド実測

**検証目的**: イベント発行(遅い・失敗するケースを含む)が、本来の処理(応答生成等を模したダミーの非同期処理)の所要時間に、実際にどの程度の影響を与えるかを、推測ではなく実測で確認する。

**実験内容**(リポジトリには一切含めていない、セッション内の使い捨てスクリプト): 意図分類(50ms)・記憶検索(80ms)・応答生成(300ms)を模した3段のダミー処理を、(a) イベント発行なし、(b) `asyncio.create_task()`によるfire-and-forgetイベント発行あり(うち1つは2秒かかる・もう1つは必ず例外を送出する、という意図的に悪いケースを含む)、の2条件で、それぞれ20回実行し、合計所要時間を比較した。

**結果**:
```
baseline (no event emission):              avg 465.16ms / turn
with fire-and-forget event emission:       avg 455.02ms / turn
difference: -10.144ms (誤差範囲内、統計的な有意差なし)
```
`asyncio.create_task()`自体の呼び出しコストは、実測ではノイズ(タイマーの揺らぎ)に埋もれる程度であり、本来の処理時間に対して測定不能なほど小さいことを確認した。また、2秒かかるイベント発行・必ず例外を送出するイベント発行のいずれも、**呼び出し元(本来の処理)の完了・戻り値には一切影響しなかった**(全20回とも、本来の処理は正常に完了)。一方で、例外を送出するタスクは、標準エラー出力に`Task exception was never retrieved`という警告を残すことを確認した——これが、上記3.1節で「イベント発行タスク自身が内部で例外を処理する必要がある」と判断した、実測に基づく根拠である。

### 3.3 配信方式の比較検討

現在のサーバー環境(`docs/infrastructure.md`・`docs/cloudflare-tunnel.md`で確認): Ubuntu Server上のuvicorn(FastAPI、単一プロセス、ポート8000)が、Cloudflare Tunnel(named tunnel、`cloudflared`をsystemdサービスとして常駐)経由で`api.sigmaris.jp`として外部公開されている。フロントエンドはVercel上のNext.js。

| 方式 | 長所 | 短所 | 判定 |
|---|---|---|---|
| **Server-Sent Events (SSE)** | **既に本番で実績がある**——`/api/agent/chat/stream`(`chat.py::stream_chat_completion_ui()`)が、全く同じ`data: {...}\n\n`形式のSSEを、同じCloudflare Tunnel経由で、既に安定稼働させている。ブラウザの`EventSource`は自動再接続を標準搭載。単方向配信(サーバー→クライアント)のみで用途に過不足がない | HTTP/1接続を1本占有し続ける(ただし個人利用規模では問題にならない) | **採用** |
| **WebSocket** | 双方向通信が可能(本用途では不要) | このコードベースに前例がなく、新規の接続管理・再接続ロジックをフロントエンド側にゼロから実装する必要がある。Cloudflare Tunnelは技術的にWebSocketもプロキシ可能だが、既存のSSE実績と比べ、追加の検証コストがかかる | 見送り |

**判断根拠**: 「安全な組み込み方」という依頼書の主旨に照らし、**新しい配信技術を導入するリスクより、既に本番で実績のある配信方式を再利用するリスクの低さを優先すべき**と判断した。同じCloudflare Tunnel経由で、同じSSE形式が、既にBA4以降のstreaming応答で毎日使われ続けている実績は、Sigmaris Liveにとって最も強い技術的根拠になる。

### 3.4 配信アーキテクチャの設計: 「誰が見るか」の分離

依頼書の背景文「シグマリスの内部処理が...外部に、可視化する」という記述から、Sigmaris Liveの観測者は、**その時チャットしている本人とは限らない**(例えば、別の画面・別の時間帯に、シグマリスの"生きている様子"を眺める、という用途も構想に含まれると解釈した)と判断した。この解釈に基づき、以下の2層構造を提案する。

1. **発行層**: `emit_live_event()`(3.1節)が、プロセス内メモリの単純なpub/subバス(`live_event_bus`、新規、`asyncio.Queue`ベース)へイベントをpublishする。サーバーは単一のuvicornプロセス(`docs/infrastructure.md`で確認済み)であるため、Redis等の外部pub/subは不要——**将来、複数ワーカー構成へ移行する場合は、この前提が崩れる**ことを、6章の懸念点として明記する。
2. **配信層**: 新設の読み取り専用SSEエンドポイント(例: `GET /api/agent/live/stream`)が、`live_event_bus`を購読し、接続してきた観測者へイベントをそのまま中継する。これは、特定のチャットリクエストのHTTP接続とは**別の**、独立した接続である。これにより、「今チャットしている人自身の画面」と「Sigmaris Liveを眺めているだけの画面」を、同じイベント発行の仕組みから、両方とも自然に配信できる。
3. 認証は、既存の`/api/agent/growth/*`と同じ`X-Agent-ID`/`X-Agent-Secret`ヘッダ方式(`app/routes/agent.py::_verify_agent()`)をそのまま再利用する想定(新しい認証機構を作らない)。

**この設計自体は未実装であり、本タスクでは`live_event_bus`・新規SSEエンドポイントいずれのコードも書いていない**(依頼書「本番コードへの変更は行わないこと」の遵守——上記は次タスクへの設計提案である)。

---

## 4. プライバシー・機密情報への配慮の設計方針

### 4.1 基本方針: 「構造」は見せるが「内容」は見せない

2.2節の表で明示した通り、全てのイベントペイロードは、**件数・真偽値・カテゴリラベルのような、構造的な要約情報のみ**を含み、以下は一貫して除外する。

- ユーザーの発言内容そのもの(`intent_classification_*`の`reason`フィールドを含む理由——このコードベースの分類系関数の`reason`は、しばしば発言の一部を引用する形式になっている)
- 記憶(`user_fact_items`)の内容・値
- Web検索のクエリ文字列・取得した引用文・URL
- ツール呼び出しの引数(位置情報・カレンダーの予定内容等、個人情報を含みうる)
- 応答本文そのもの(既に本人にはstreamingで見えているが、外部の観測者向けイベントには含めない——4.2節で詳述)

この方針は、H-2(`x_reply_filter.py`)が確立した「判定結果は記録するが、判定に使った生テキストの詳細を`filter_reasons`という短いラベルの配列に留める」という設計、及びH-2.5が確立した「一般ユーザー向け生成には、そもそも記憶を入力しない」という構造的な非漏洩の考え方を、踏襲したものである。

### 4.2 「応答本文を、外部観測用イベントに含めない」判断根拠

`response_generation_finished`イベントは、応答の文字数(`response_length`)のみを含み、本文そのものは含めない設計とした。判断根拠: 3.4節の設計では、Sigmaris Liveの観測者が、その時チャットしている本人と異なりうる。もし応答本文をイベントに含めた場合、**チャットしている本人が意図しない相手にも、会話内容が筒抜けになる**——これはH-2.5が一般ユーザー向け返信生成で徹底した「個人情報を、想定していない相手に晒さない」という原則と、本質的に同じ懸念である。本人がチャットしている画面自体には、既存のSSE(`/api/agent/chat/stream`)で応答本文がそのまま届くため、情報が失われるわけではない——Sigmaris Live側のイベントストリームだけが、内容を含まない設計になる。

### 4.3 「詳細を、クリックして、見る」機能(将来のLive-3相当)に向けた設計方針

依頼書が見据える将来機能について、以下の分離方針を提案する。

- **概要情報(本タスクの対象)**: 3.4節のSSEで、全観測者へ**無差別に**配信される。プライバシーに配慮し、常に4.1節の要約情報のみを含む。
- **詳細情報(将来のLive-3相当)**: SSEのイベントには含めず、`invocation_id`(+必要ならイベント種別)をキーとした、**別の、認証済みREST APIへの、都度リクエスト**として設計すべきと考える。既存の`/api/agent/growth/*`と同じ`X-Agent-ID`/`X-Agent-Secret`認証に加え、**海星さん本人のユーザーJWTによる、本人確認も必須にすべき**(SSEの配信層で使う`X-Agent-ID`はエージェント間通信の認証であり、「どの人間が見てよいか」までは区別しない——`_require_jwt()`の既存パターン(`app/routes/agent.py:88-94`)を、詳細取得エンドポイントには必ず追加する設計にする)。

この分離により、「誰でも(エージェント認証さえあれば)概要は見られるが、詳細(記憶の中身・会話内容等)は本人のJWTがなければ見られない」という、2段階のアクセス制御が実現できる。

---

## 5. 「途中経過」の見せ方の設計(本物のリアルタイム性と、演出の境界線)

### 5.1 応答生成: 本物のリアルタイム性が、既に存在する

`response_generation`段階(1章⑦)は、`chat.py`の`client.responses.create(..., stream=True)`が、OpenAI側から実際にトークンを受け取るたびに、即座に`text-delta`イベントとしてyieldしている(`chat.py:1154-1164`)。BA4完了後、この`delta`は`orchestrator/service.py`でバッファリングされず即座に中継されることを、コード上確認済み(1章④、`service.py:1636-1640`)。**この経路は、そのままSigmaris Liveの表示にも使える、正真正銘の「今まさに生成されている」途中経過である。** 新しい実装は不要で、既存のstreaming配信を、そのまま可視化に転用すればよい。

### 5.2 記憶検索・意図分類・Evidence検索: 瞬間的に完了する処理であることの確認

コードを直接確認した結果、以下が判明した。

- **記憶検索(`search_with_decomposition`)**: `search_relevant_memories()`内部の`generate_embedding()`‖trgm検索は並列実行され、その後のvector検索RPCは1回のDB呼び出しである。**複数件の記憶が、時間差で1件ずつ見つかるという実装には、そもそもなっていない**——RPCが返す時点で、上位N件が既に確定した状態で一括で返る。
- **Evidence検索(`gather_search_evidence`)**: `run_web_search()`(1回のLLM呼び出し)→`structure_evidence()`(1回のLLM呼び出し)という、直列2段の**バッチ処理**であることを、`evidence_search.py:263-287`・`177-`で確認した。複数の引用(citation)が見つかった場合でも、**それらは同時に(1回のLLM呼び出しの結果として)まとめて確定する**——個々の引用が、実際に1件ずつ順番に見つかっていくという処理には、なっていない。
- **意図分類(`classify_chat_intent`)**: ヒューリスティックは即座に、LLM呼び出しの場合も1回のAPI呼び出しで一括して`intent`が確定する。「候補を絞り込んでいく過程」のような、段階的な処理は存在しない。

**結論: 記憶検索・Evidence検索・意図分類のいずれも、"実際にあった複数の結果を、1件ずつ時間差で表示する"という演出の材料にできる、本物の段階的な結果は、現在の実装には存在しない。** 仮にこれらの処理結果を「1件ずつ、時間差で」表示した場合、それは依頼書が明確に禁止する「本当は瞬時に終わっているのに、意図的に遅延を作り出して"考えている風"に見せる」ことに該当する。**本タスクでは、これらの段階については、`started`(開始)→(実際の所要時間だけ待つ)→`finished`(終了、件数等の要約を伴う)という、正直な二値の表示に留めるべきと結論する。**

### 5.3 UI上での視覚的な区別(設計方針の提案、実装はしていない)

上記2種類の性質を、観測者が混同しないための工夫として、以下を提案する(コードは書いていない、次タスクへの設計提案)。

- **response_generation**: 文字が実際に、届いた分だけ、そのままの速度で画面に追記されていく、従来通りのタイピング風表示(演出ではなく、本物の生成速度をそのまま反映)。
- **memory_search / intent_classification / evidence_search**: 「◯◯を確認しています」のような、進行中を示す**単一の**インジケータ(スピナー等)を`started`受信時に表示し、`finished`受信時に、要約情報(例:「記憶を3件確認」「検索が必要と判断」)を**一度に**表示して次の段階へ切り替える。個々の記憶やcitationを1件ずつフェードインさせるような演出は、5.2節の結論に基づき、意図的に採用しない。
- 上記の区別により、観測者が「文字がゆっくり出ている」ものは本物の生成中、「短い要約が一度に切り替わる」ものは瞬時の判定・検索の結果である、と自然に区別できることを狙う。この区別自体を明示的な凡例やラベルとして画面上に示すかどうかは、フロントエンド設計の裁量に委ねるべき事項と考え、本タスクでは具体的なUIコンポーネント設計までは踏み込まない。

---

## 6. 段階的な導入計画の提案

### 6.1 最初に着手すべき処理: `classify_chat_intent()`(意図分類)

以下の根拠により、**意図分類(1章⑤)を、最初に試験的に導入すべき処理として提案する。**

1. **既存調査が、これを最大のボトルネックとして既に特定している**: `incident_response_latency_investigation.md`7〜11章が、`classify_chat_intent()`を「実測で全体の約4割(8.3秒/20.3秒)を占め、かつユーザーには完全に不可視の非ストリーミング呼び出しである」(同報告書7.5節)と結論づけている。11章でnano階層への移行を実施済みだが、それでも「ヒューリスティックで判定しきれない場合はLLM呼び出しが発生する」という構造自体は変わっていない。
2. **現在、最も"何も見えない"処理である**: `emit_status_delta=False`(`chat.py`の呼び出し元、`app/routes/agent.py`付近)により、この間ユーザーには文字通り何も表示されない。Sigmaris Liveが「今何をしているか」を見せる意義が、他のどの段階よりも大きい。
3. **実装上のリスクが最も低い**: 呼び出し箇所が`chat.py:1003-1006`の1箇所に閉じており、応答生成のstreamingループ(⑦、最もデリケートな、直接ユーザー体感に影響する箇所)には一切触れずに済む。ヒューリスティック分岐(`source: "heuristic"`)により、`started`→`finished`が数ミリ秒で完了するケースと、数秒かかるケースの両方が、実運用で自然に観測でき、Sigmaris Liveの「速い時と遅い時がある」という、誠実な可視化の初期検証にも適している。
4. **記憶検索(③)より対象範囲が狭い**: 記憶検索は、B7(条件付きLLM)・B9(文字列処理)・B10(条件付きLLM)・B11(判定)・B12(圧縮)・Temporal(条件付きDB)という、複数のサブステージが入れ子になっている(1章③)。最初の導入対象としては、意図分類という単一のサブステージの方が、設計・実装・検証のいずれにおいても扱いやすい。

### 6.2 導入後、次に拡張すべき候補(優先順位)

1. `response_generation_started`/`finished`(⑦): 既存のtoken streamingをそのまま活用でき、実装コストが低い。ただし依頼書の設計方針上、これは他の段階と異なり「演出」ではなく「実際のstreaming中継そのもの」であるため、Sigmaris Live用の新しいイベント種別というより、既存のSSEチャンクを、Live側の表示にも流用する形の実装になる可能性が高い(3.4節の配信層設計と合わせて再検討すべき)。
2. `memory_search_started`/`finished`(③): ①より複雑だが、依頼書の背景(記憶検索が可視化の重要な題材として明示的に例示されている)を踏まえ、次点で着手する価値が高い。
3. `evidence_search_started`/`finished`(⑥)・`tool_call_started`/`finished`: いずれも発生頻度が低い(条件付き)ため、優先度は①②より低いが、実装自体はシンプル。

---

## まとめ

- 既存の処理フローを、現在のコードに基づき正確に整理した(1章)。依頼書の例示イベント順と、実際のコードの時系列は異なる(記憶検索が意図分類より先)という、調査でしか分からなかった事実を明記した。
- 12種類のトップレベルイベントと、各イベントに含めるべき/含めるべきでないデータを設計した(2章)。
- fire-and-forgetパターンの安全性を、実際の実験(3.2節)で実測確認した上で、SSE(既存の`/api/agent/chat/stream`と同じ、実績のある方式)による、発行層/配信層を分離した配信アーキテクチャを提案した(3章)。
- 全イベントが要約情報のみを含み、内容(発言・記憶・応答本文等)を一切含まない設計とし、将来の詳細表示機能は、別の認証済みREST APIとして分離すべきという方針を示した(4章)。
- 応答生成のみが本物のリアルタイム性を持ち、記憶検索・意図分類・Evidence検索はいずれも瞬間的に完了するバッチ処理であることをコードで確認し、後者を偽って段階的に見せる演出は行うべきでないと結論した(5章)。
- 最初の試験導入対象として、既存調査が最大のボトルネックと特定し、かつ現在最も不可視で、実装リスクも最も低い、意図分類(`classify_chat_intent()`)を提案した(6章)。

**次のタスクへの申し送り**: 本タスクでは、`emit_live_event()`・`live_event_bus`・新規SSEエンドポイントのいずれも実装していない。次タスク(Live-2相当)では、まず6.1節で提案した意図分類の1箇所にのみ、最小のイベント発行を試験的に組み込み、実運用での挙動(観測者への配信遅延・接続安定性等)を確認してから、他の段階へ拡張することを推奨する。

---

# Sigmaris Live Live-2 実施報告: 最初のイベント発行の試験的な導入

Live-1が提案した設計に基づき、`classify_chat_intent()`にのみ、実際にイベント発行・SSE配信を実装した。他の処理(記憶検索・応答生成等)には、依頼書の指示通り一切手を加えていない。

## 7. イベント発行の実装詳細

### 7.1 新設モジュール: `backend/app/services/live_events.py`

Live-1、3.1〜3.2節の設計をそのまま実装した。

- `LiveEventBus`(dataclass): プロセス内メモリの、単純なpub/subバス。`_subscribers: set[asyncio.Queue]`を保持し、`subscribe()`/`unsubscribe()`/`publish()`の3メソッドのみを持つ。
- `publish(event)`: 同期・非I/O(インメモリのキュー操作のみ)。接続中の全観察者のキューへ`put_nowait()`する。キューが満杯(`maxsize=100`)の観察者にはこのイベントをスキップし、`logger.warning()`のみ行う(例外は送出しない——観察者側の受信遅延が、発行側や他の観察者に一切影響しないための設計)。
- `emit_live_event(event_type, invocation_id, **fields)`: fire-and-forgetの入口。`asyncio.create_task(_publish_live_event(...))`のみを行う同期関数。
- `_publish_live_event(...)`: タスク本体。`try/except`で自己完結し、失敗しても外部(呼び出し元・asyncioのタスク管理)に一切伝播しない。イベント本体(`event`/`invocation_id`/`timestamp`+可変フィールド)は、この関数の中で組み立てる。

### 7.2 呼び出し箇所: `backend/app/services/chat.py`

`stream_chat_completion_ui()`内、`classify_chat_intent()`の呼び出し(既存のコード、変更前は1005-1008行目)を、`emit_live_event()`の呼び出しで挟む形にした。

```python
_live_event_started_at = time.perf_counter()
emit_live_event("intent_classification_started", message_id)
route = await classify_chat_intent(
    messages=messages,
    attachment_facts=attachment_facts,
)
emit_live_event(
    "intent_classification_finished",
    message_id,
    intent=route["intent"],
    source=route["source"],
    needs_search=bool((route.get("search") or {}).get("needs_search")),
    elapsed_ms=int((time.perf_counter() - _live_event_started_at) * 1000),
)
```

`classify_chat_intent()`関数自体(`chat_routing.py`)は、1行も変更していない——依頼書「既存の意図分類の処理速度・精度に一切悪影響を与えないこと」への対応として、既存の、慎重に軽量化されてきた関数の内部には触れず、その呼び出し元(1箇所のみ)を挟む形に徹した。

**判断根拠1: 非streaming経路(`run_chat_completion()`)には、あえて手を加えていない。** `chat.py`には`classify_chat_intent()`の呼び出しが2箇所存在する(streaming用の`stream_chat_completion_ui()`と、非streaming用の`run_chat_completion()`)。Live-1が「リアルタイムな可視化」の対象として想定していたのは、実際に応答が生成されている最中に画面へ反映される、streaming経路である。非streaming経路(WearOS等、`docs/sigmaris/phase_ba4_report.md`で言及)には、そもそもSigmaris Liveを見ながら使うという利用形態が想定されないと判断し、依頼書「他の処理には手を加えないこと」を、対象範囲を広げない方向で厳格に解釈した。

**判断根拠2: `invocation_id`には、`orchestrator/service.py`が発行する真の監査ログID(`invocation_id`)ではなく、`chat.py`内で既に生成済みの`message_id`を代用した。** 真のIDは、`schedule_agent_client.py`が`X-Correlation-ID`ヘッダとして送信済みだが、受け手の`routes/agent.py::agent_chat_stream()`は、現時点でこのヘッダを読んでいない。これを読むよう変更するには、共有ホットパスである`agent_chat_stream()`のシグネチャ変更が必要になり、依頼書が求める「本タスクの範囲は`classify_chat_intent()`のみ」という厳格な限定から外れる、既存の本番エンドポイントへの追加リスクだと判断した。`message_id`は、1ターン内でのイベント相関(`started`→`finished`の対応付け)には十分に機能するが、`orchestrator/audit.py`の監査ログとは突き合わせられない、という制約が残る(9章に申し送り)。

## 8. SSE配信の実装詳細(publish/subscribe分割の実現方法)

Live-1、3.3〜3.4節の設計に基づき、発行層(7章)とは独立した配信層を実装した。

### 8.1 バックエンド: `GET /api/agent/live/stream`(`backend/app/routes/agent.py`)

既存の`/api/agent/growth/*`と同じ`_verify_agent(x_agent_id, x_agent_secret)`のみで認証する(Live-1、4.3節の設計通り、配信されるデータが要約情報のみのため、ユーザーJWTによる本人確認は不要と判断——将来の詳細取得エンドポイントでのみ追加すべき、という方針を踏襲した)。接続ごとに`bus.subscribe()`で専用の`asyncio.Queue`を取得し、`while True: event = await queue.get()`でイベントを待ち受け、`data: {...}\n\n`形式(既存の`/api/agent/chat/stream`と全く同じSSE形式)でyieldし続ける。接続が切れた場合は`finally`節で確実に`unsubscribe()`する。

これにより、**このエンドポイントへの接続(観察者)と、実際にチャットしている`/api/orchestrator/chat/stream`への接続は、完全に独立したHTTP接続になる**——Live-1、3.4節が提案した「観察者の視点とチャットしている接続の分離」を、そのまま実現した。

### 8.2 フロントエンド: `/api/live/stream`(Next.js API Route)+ `/live`(確認用ページ)

- `frontend/src/app/api/live/stream/route.ts`(新設): サーバーサイドで、既存の`agent-client.ts::readAgentHeaders()`(`/growth`ページが使うものと全く同じ関数)を使い、エージェント認証ヘッダ付きでバックエンドのSSEへ接続し、`upstream.body`(`ReadableStream`)を、加工せずそのままブラウザへ中継する。**エージェント認証情報は、サーバーサイドの環境変数からのみ読み、ブラウザには一切渡さない**(既存の`/growth`・`/timeline`ページと同じ設計方針)。`EventSource`(ブラウザAPI)はカスタムヘッダを付与できないため、この中継層が必須になる。
- `frontend/src/app/live/page.tsx`(新設)+`frontend/src/components/live/live-event-log.tsx`(新設): `requireUser()`(既存の認証ガード)で保護した、最小限の確認用ページ。`new EventSource("/api/live/stream")`で接続し、受信した各イベントを、直近200件までのテキストログとして画面に表示するのみ。**依頼書の指示通り、本格的なSigmaris Live画面(点灯・メトリクス・グラフ等)は実装していない。** ナビゲーション(`app-shell.tsx`)にもリンクを追加していない(確認用の一時的なページと位置づけたため)。

### 8.3 判断根拠: なぜチャット自身のSSE接続に相乗りせず、別接続にしたか

Live-1、3.4節で検討した「同一クライアントへは、チャット自身のSSEストリームに`live_event`フィールドを追加する形でも配信できる」という代替案は、本タスクでは採用しなかった。判断根拠: (a) 依頼書が明示的に「観察者の視点と、実際にチャットしているユーザーの接続が分離される、というLive-1の提案を踏まえた設計にすること」を要件として指定しており、まず分離された設計を実装することが本タスクの直接の要求だと判断した。(b) 相乗り方式は、`orchestrator/service.py`の`OrchestratorStreamEvent`(既存のdelta/tool_event/done)にフィールドを追加する必要があり、これも「他の処理には手を加えないこと」が禁じる範囲に近い、共有インフラへの変更になる。独立したSSEエンドポイントは、既存のチャットストリームに一切触れずに実現できる、最も低リスクな選択肢だった。

## 9. 処理速度への影響の確認結果

依頼書「可能であれば、処理速度への影響を実測、または見積もる」への対応として、Live-1の実験(シミュレーション)ではなく、**実際に実装した`emit_live_event()`そのものを直接計測**した。

```
2000回のstarted+finishedペア呼び出し(観察者接続なし):
  合計 13.57ms、1ペアあたり平均 6.79マイクロ秒

同条件、観察者(SSE購読者)が1つ接続された状態:
  合計 14.48ms、1ペアあたり平均 7.24マイクロ秒
```

`classify_chat_intent()`自体は、ヒューリスティックで即座に終わる場合でも数ミリ秒〜数十ミリ秒、LLM呼び出しにフォールバックする場合は`incident_response_latency_investigation.md`の実測で数秒(場合によっては8秒超)かかる処理である。今回追加した`emit_live_event()`2回分のオーバーヘッド(合計で1桁マイクロ秒オーダー)は、**いずれのケースでも、処理全体の所要時間に対して測定不能なほど小さい**(最も速いヒューリスティック経路と比較しても、1000分の1以下)。

また、観察者が接続していても、いなくても、オーバーヘッドはほぼ変わらない(6.79μs vs 7.24μs、誤差の範囲内)ことを確認した——`publish()`が接続中の観察者数に対して線形の処理(`for queue in list(self._subscribers):`)であるため、観察者が極端に多くない限り(本システムは個人利用規模のため現実的でない)、この結論は変わらないと考える。

**追加で判明した挙動(9.1で申し送り)**: 観察者が接続したままイベントを受信し続けない場合(`queue.get()`を呼ばれない状態が続く場合)、`_QUEUE_MAXSIZE`(100件)に達した時点から、`publish()`のたびに`logger.warning("live_events: subscriber queue full, dropping event")`が出力され続けることを、意図的にキューを枯渇させる実験で確認した。実際のSSEエンドポイント(8.1節)は`while True: await queue.get()`で継続的に消費し続けるため、正常系では発生しない挙動だが、観察者側の接続が実質的にハングした場合(受信を止めたがTCP接続自体は残っている等)には、警告ログが継続的に出力される可能性がある——これは9.1節の懸念点として明記する。

## 10. テスト結果

`test_sigmaris_live_2_intent_classification_pilot.py`に15件のテストを新設した。既存テストとあわせて、全688件(Live-1までの673件+新規15件)が成功した。回帰は発生していない。

サンプル(要件ごと):

- **要件1(`classify_chat_intent()`にのみ、試験的にイベント発行が追加されること)**: `test_emits_started_then_finished_around_classify_call` — `stream_chat_completion_ui()`を実行し、`classify_chat_intent()`の呼び出し前後で、正確に2回(`intent_classification_started`→`intent_classification_finished`)`emit_live_event()`が呼ばれることを確認。
- **要件2(処理速度・精度への非影響)**: `test_classify_chat_intent_receives_unmodified_arguments`(渡される引数が一切変更されていないこと)・`test_route_result_is_used_unchanged_downstream`(戻り値`route`が、既存の後続処理`build_specialized_router_instruction()`へ、そのまま正しく渡ること)。
- **要件(イベント発行の失敗が、本来の処理に影響しないこと)**: `test_bus_publish_exception_does_not_affect_caller` — `LiveEventBus.publish()`自体が例外を送出するよう意図的に細工した状態で、`stream_chat_completion_ui()`全体を実行し、応答生成が正常に完了する(`finishReason: stop`まで到達する)ことを確認。`test_failing_publish_does_not_leave_unhandled_task_exception` — 失敗時にも、タスク自身が例外を握りつぶすことを確認。
- **要件3(SSE配信)**: `LiveEventBusDeliveryTests`(5件、subscribe/publish/unsubscribe・複数観察者への同時配信・キュー満杯時の非例外的なドロップ・`emit_live_event()`からの end-to-end到達)、`LiveStreamRouteTests`(2件、`_verify_agent()`による認証の必須化・`StreamingResponse`が正しい`media_type`で返ること)。
- **要件4(生データを含まないこと)**: `test_finished_event_payload_contains_only_summary_fields` — ペイロードに`intent`/`source`/`needs_search`/`elapsed_ms`のみが含まれ、`reason`(自由文)やユーザー発言そのものが含まれないことを確認。
- **要件5(他の処理には手を加えないこと)**: 記憶検索・応答生成関連のコードは一切変更していない(既存694件級のテストが無変更で成功していることが、その裏付け)。
- **要件6(既存機能への非影響)**: 既存688件(Live-2までの回帰込み)が全て成功。フロントエンドは`npx eslint`・`npx tsc --noEmit`のいずれもエラーなしを確認。

## 11. 気づいた懸念点・次のステップ(Live-3以降、他の処理への拡大)に向けた申し送り事項

1. **`invocation_id`が、`orchestrator/service.py`の真の監査ログIDと一致しない(7.2節、判断根拠2)。** 次タスクで他の処理(記憶検索等、`orchestrator/service.py`側で発生する処理)にイベント発行を拡大する際は、そちら側では真の`invocation_id`が既に手元にあるため問題にならないが、`chat.py`側のイベント(意図分類・応答生成・Evidence検索)と、`orchestrator/service.py`側のイベント(記憶検索等)を、同一ターンとして相関させたい場合、`X-Correlation-ID`ヘッダを`agent_chat_stream()`が実際に読み取り、`chat.py`へ引き渡す変更が、いずれ必要になる。本タスクでは、この変更を意図的に見送った(判断根拠、7.2節)。
2. **観察者が受信を止めた場合の警告ログ(9章末尾)。** 現状は`logger.warning()`が無制限に出続ける設計である。実運用で問題になる場合は、同一観察者に対する警告を一定間隔に間引く、または一定回数のドロップでそのキューを強制的に`unsubscribe()`する、といった対策を、次タスクで検討する余地がある。
3. **複数ワーカー構成への非対応(Live-1、3.4節で明記済みの制約の再確認)。** `LiveEventBus`はプロセス内メモリのみで動作するため、`docs/infrastructure.md`で確認した現在の単一uvicornプロセス構成が前提。将来、複数ワーカー構成へ移行する場合は、Redis pub/sub等への置き換えが必要になる。
4. **`/live`確認用ページは、意図的に最小限に留めた(依頼書の指示通り)。** 本格的なSigmaris Live画面の設計・実装は、次タスク(Live-3以降)の範囲とする。UI設計(Live-1、5.3節で提案した「本物のstreamingと、瞬時の判定を、視覚的に区別する」工夫等)は、今回のテキストログ表示には反映していない。
5. **実際のOpenAI APIキー・実Ollama環境での検証は、依頼書の制約により行っていない。** `classify_chat_intent()`自体の応答は全てモックであり、実モデルでの意図分類の所要時間そのものへの影響(理論上ゼロのはずだが)は、本番環境での実測を推奨する。
6. **次タスクへの提案: Live-1、6.2節が示した優先順位(応答生成→記憶検索→Evidence検索/ツール呼び出し)を踏襲しつつ、まずは`/live`ページを実際にしばらく運用し、意図分類のイベントが安定して配信され続けること(接続の安定性・警告ログの発生頻度等)を確認してから、次の処理へ拡大することを推奨する。**

---

# Sigmaris Live Live-3 実施報告: 本格的なフロントエンド表示への発展

**作業ブランチ:** `sigmaris-live-3-frontend-flow`(mainから新規作成)
**範囲:** Live-2の最小限の確認用ページ(テキストログのみ)を、処理の流れの視覚化・整理されたログ・簡単なメトリクスを備えた画面へ発展させる。**バックエンドの変更は一切行っていない**——Live-2が実装済みのイベント発行・SSE配信(`live_events.py`・`routes/agent.py::/live/stream`・`frontend/src/app/api/live/stream/route.ts`)を、そのまま使う。対象は引き続き`classify_chat_intent()`のみ。

---

## 12. 前提として確認したこと

着手前に、以下を実際のコードで確認した。

- `docs/sigmaris/sigmaris_live_report.md`(Live-1・Live-2、7〜11章)
- `backend/app/services/live_events.py`: `_publish_live_event()`が実際に送信する`timestamp`は、Live-1の設計メモに書かれていたISO文字列例("2026-07-18T...")ではなく、**`time.time()`(epoch秒、float)そのものである**ことを確認した。Live-2のフロントエンド実装(旧`live-event-log.tsx`)は、この値を`toLocaleTimeString()`等で加工せず、受信時刻(`new Date()`)を別途記録して表示していたため、この差異による実害は無かったが、Live-3では`timestamp`自体を表示に使うため(ログの時刻列)、この単位の違いを先に確認しておく必要があった。
- `backend/app/services/chat.py:1028-1041`: `intent_classification_finished`が実際に送るフィールドは、報告書2.2節の設計通り`intent`/`source`("heuristic"|"llm")/`needs_search`/`elapsed_ms`のみであることを再確認した。
- `frontend/src/app/growth/page.tsx`・`frontend/src/components/app-shell.tsx`: 既存のデザインシステム(配色トークン・`Section`/`StatCard`パターン・`AppShell`のナビゲーション構成)を確認した。

---

## 13. 視覚的なフロー表示の実装詳細

### 13.1 拡張可能な設計: `PROCESS_STEPS`設定配列

`frontend/src/components/live/process-steps.ts`(新設)に、対象処理の一覧を**データとして**定義した。

```typescript
export const PROCESS_STEPS: readonly ProcessStepConfig[] = [
  {
    id: "intent_classification",
    label: "意図分類",
    description: "会話の意図(カレンダー登録・予定確認等)を判定します",
    startedEvent: "intent_classification_started",
    finishedEvent: "intent_classification_finished",
  },
  // 将来の処理(記憶検索・Evidence検索・応答生成等)は、ここに1エントリ
  // 追加するだけで反映される
] as const;
```

**判断根拠(依頼書1章「将来複数の処理が追加された際に自然に拡張できるレイアウトを意識すること」への対応)**: `LiveProcessFlow`コンポーネント自体は、この配列を`map`して横並びに描画するだけで、`intent_classification`という特定の処理名を(結果の要約整形を除き)ハードコードしていない。次タスク(Live-4)が記憶検索等を追加する際、この配列に1件追加するだけで、フロー表示・メトリクス表示の両方に自然に反映される設計にした。

### 13.2 状態計算: `computeStepStates()`(純粋関数)

イベント配列を時系列順に走査し、各処理の現在の状態(`idle`/`active`/`done`)を導出する、副作用のない純粋関数として実装した(`process-steps.ts`)。`_started`イベントで`active`、`_finished`イベントで`done`に遷移する、単純な状態機械である。

### 13.3 「本物のリアルタイム性」と「演出」の境界線(依頼書の重要な制約への対応)

`active`状態の表示(`live-process-flow.tsx`の`StepDot`)は、紫色の円がパルスしながらスピナーが回転する、**進捗の割合を示さない、不定形の「実行中」インジケータ**にした。

**判断根拠**: Live-1、5.2節が既に確認していた通り、`classify_chat_intent()`は「候補を絞り込んでいく」ような段階的処理ではなく、ヒューリスティックまたは1回のLLM呼び出しで一括して完了するバッチ処理である。仮に「0%→100%」のようなプログレスバーを実装すると、実際には存在しない「どれだけ進んだか」という情報を捏造することになり、依頼書が禁じる演出に該当する。そのため、**実際に`_started`イベントを受信してから`_finished`イベントを受信するまでの、正味の実時間だけ**表示される、不定形スピナーに留めた。`done`になった瞬間、要約結果(`intent`・判定方式・所要時間)を**一度に**表示する——Live-1、5.3節が提案した「個々の結果を1件ずつフェードインさせる演出は採用しない」という設計方針を、そのまま踏襲した。

### 13.4 結果要約表示

`done`状態では、`intent_classification_finished`イベントのペイロードから、`{intent}({判定方式}{検索要否}) ・ {所要時間}`という1行の要約を組み立てて表示する(例: `event_lookup(LLM判定・検索要) ・ 2350ms`)。専門用語(`source: "llm"`等)は「LLM判定」「即時判定」という日常語に置き換えた。

---

## 14. ログ表示の改善内容

`frontend/src/components/live/live-event-log.tsx`を、以下の観点で書き直した。

1. **表形式への変更**: Live-2の生JSON文字列表示(`JSON.stringify(line.raw)`)を廃し、依頼書2章「時刻・処理名・簡単な結果が見やすく並ぶ」形の、3列テーブル(時刻・処理名・結果)にした。
2. **処理名の日本語ラベル化**: `EVENT_LABELS`(定数マップ)で、`intent_classification_started` → 「意図分類 ・ 開始」のように変換する。将来の処理追加時は、このマップにエントリを追加するだけでよい。
3. **結果列の要約整形**: `finished`イベントは13.4節と同じ要約文字列、`started`イベントは「実行中...」、解析に失敗したイベントは「配信データの解析に失敗しました」と表示する。
4. **新しい順に表示**: Live-2は受信順(古い→新しい)にログを積んでいたが、Live-3では表示直前に配列を反転させ、**最新のイベントが常に一番上**に来るようにした(ログとして自然な順序、判断根拠として明記——依頼書に明示的な指定は無いが、一般的なログ・監視画面の慣習に合わせた)。

### 14.1 データソースからの分離(重要な設計変更)

Live-2の`LiveEventLog`は、コンポーネント自身が`new EventSource(...)`を呼び、SSE接続を保持していた。Live-3では、この接続保持ロジックを`use-live-events.ts`(新設フック)へ切り出し、`LiveEventLog`は`events: LiveEvent[]`をpropsで受け取るだけの、**データソースを知らない純粋な表示コンポーネント**に変更した。この設計変更の判断根拠は、15章(デモ用の配慮)で詳述する。

---

## 15. メトリクス表示の実装内容

### 15.1 算出内容(既存のイベントデータのみを使用)

`frontend/src/components/live/metrics.ts`(新設)の`computeStepMetrics()`が、依頼書2章3節「直近の意図分類にかかった時間」の例示に沿って、以下の4種類を算出する。**新しいデータ収集は一切行っていない**——`intent_classification_finished`が既に持つ`elapsed_ms`/`source`フィールド(Live-2で実装済み)を、フロントエンド側で集計するのみ。

1. **直近の所要時間**: 最新1件の`elapsed_ms`。
2. **平均所要時間**: 直近20件(既定値)の`elapsed_ms`の平均。
3. **即時判定件数**: `source: "heuristic"`の件数(直近20件中)。
4. **LLM判定件数**: `source: "llm"`の件数(同上)。

**判断根拠(件数「20件」を選んだ理由)**: 依頼書は具体的なサンプル数を指定していない。20件は、直近数分〜数十分程度の会話量に相当する、「直近の傾向」として意味を持つが、極端に古いデータに引きずられない範囲として、独断で選んだ値である(将来調整が必要になった場合、`computeStepMetrics()`の`sampleSize`引数を変えるだけで済む設計にした)。

### 15.2 「即時判定 vs LLM判定」の比率を含めた判断根拠

依頼書は「直近の意図分類にかかった時間」を例示のみとしていたが、`incident_response_latency_investigation.md`(Live-1が参照した既存調査)が`classify_chat_intent()`を最大のボトルネックと特定した根本原因は、**「ヒューリスティックで判定しきれない場合にLLM呼び出しにフォールバックし、そちらが数秒かかる」という構造**にある(Live-1、6.1節)。そのため、単なる所要時間の平均だけでなく、**「今、どれだけの割合がLLMにフォールバックしているか」**も、この処理の健全性を一目で把握する上で意味のあるメトリクスだと判断し、追加した。

---

## 16. デモ用の配慮についての設計メモ(将来のLive-7への布石)

依頼書4章の指示通り、**本タスクでは模擬データ表示の実装は行っていない。** 代わりに、以下の疎結合設計を行った。

### 16.1 「データソースを知るコンポーネント」を1つに限定する設計

```
useLiveEvents()  ← 実際のSSE接続(/api/live/stream)を知る、唯一のフック
      ↓ { events, status }
LiveDashboard    ← useLiveEvents()を呼ぶ、唯一のコンポーネント
      ↓ events props
LiveProcessFlow / LiveMetrics / LiveEventLog
      ↑ いずれも「events配列を受け取って描画するだけ」の純粋な表示コンポーネント
        (データがどこから来たかを一切知らない)
```

**判断根拠**: この構造により、将来Live-7が「個人情報を含まない模擬データ」を表示したくなった場合、同じ`{ events, status }`という形を返す別のフック(例: `useMockLiveEvents()`、固定のサンプルイベント配列をタイマーで少しずつ`setState`する等の実装が想定される)を用意し、`LiveDashboard`(または新設する`LiveDashboard`のデモ版)がそちらを呼ぶように差し替えるだけで対応できる。**`LiveProcessFlow`・`LiveMetrics`・`LiveEventLog`の3つは、一切変更する必要がない。** これは、Live-2の`LiveEventLog`がSSE接続を自前で持っていた設計(データソースと表示が密結合だった)からの、意図的な方向転換である。

### 16.2 本タスクで実装した動作確認における、この設計の実際の活用

この疎結合設計は、机上の設計に留まらず、**本タスク自身の動作確認でも実際に活用した**(18章で詳述)。実モデルAPIが無い環境でも、`window.EventSource`を差し替え可能なフェイク実装に置き換えるだけで、`LiveDashboard`以下のコンポーネント一式を、実際のSSE接続を一切必要とせずに動作確認できた——これは、まさにLive-7が模擬データで行いたいことと、技術的に同じ種類の差し替えである。

---

## 17. テスト結果

### 17.1 静的検証

```
npx eslint src/components/live src/app/live   → エラーなし
npx tsc --noEmit(フロントエンド全体)          → エラーなし
npx next build                                → 成功(全42ルート、/liveを含む)
```

### 17.2 ロジックの検証(`computeStepStates`・`computeStepMetrics`)

このプロジェクトにはフロントエンド用の単体テストランナー(jest/vitest等)が導入されていない(`package.json`の`scripts`は`dev`/`build`/`start`/`lint`のみ)ため、Live-1〜2までの前例には無かった検証方法として、**同じアルゴリズムをNode.jsの素のスクリプトとして再現し、実際に実行して検証**した(scratchディレクトリ、リポジトリには追加していない)。

```
PASS: no events => idle
PASS: started only => active
PASS: activeSinceMs = timestamp*1000
PASS: started+finished => done
PASS: lastFinishedEvent carries the payload
PASS: activeSinceMs cleared once done
PASS: new turn's started flips back to active
PASS: unrelated events do not affect intent_classification's state
PASS: lastElapsedMs = most recent finished event's elapsed_ms
PASS: averageElapsedMs correct
PASS: heuristicCount correct
PASS: llmCount correct
PASS: sampleCount correct
PASS: empty events => lastElapsedMs null
PASS: empty events => averageElapsedMs null
PASS: empty events => sampleCount 0
PASS: sampleSize window caps sampleCount at 20 out of 25

ALL PASSED (16/16)
```

### 17.3 実際にブラウザを起動しての動作確認(依頼書の「実際にchatで会話し、/liveページで確認する」への対応)

実際に`/chat`で会話するには`OPENAI_API_KEY`が必要であり、依頼書の制約により追加取得は行っていない。その代わり、**16.2節の疎結合設計を利用し、`window.EventSource`をブラウザ上でフェイク実装に差し替えることで、実際にSSE経由で届くイベントと同じ形のデータを、実際のUIコンポーネントへ流し込んで検証した**(Playwright、`chromium`をヘッドレス起動)。

手順:
1. Next.js開発サーバーを起動。
2. (認証を回避するための、コミットしない一時的な確認用ルートを経由して)`LiveDashboard`を表示。
3. `window.EventSource`を、`onmessage`を外部から呼び出せるフェイク実装に差し替え。
4. `intent_classification_started` → (実際に150ms待つ) → `intent_classification_finished`(`intent: "calendar_write", source: "heuristic", elapsed_ms: 42`)を模擬発行し、スクリーンショットを取得。
5. 続けて2ターン目(`intent: "event_lookup", source: "llm", elapsed_ms: 2350`)を模擬発行し、スクリーンショットを取得。
6. `console --errors`相当(`page.on("console"/"pageerror")`)でエラーが無いことを確認。
7. **確認用の一時ルート・検証スクリプトは、いずれも本タスクの成果物ではないため、検証後にすべて削除し、`git status`で作業ツリーがLive-3の本来の変更のみになっていることを確認した。**

確認できたこと(実際のスクリーンショットで直接確認):
- idle状態: 「意図分類」ステップが灰色の`•`、「待機中」ラベル、メトリクスは「まだデータがありません」、ログは「まだイベントを受信していません」。
- active状態: 紫色の円がパルスしながら、スピナーアイコンが回転(疑似プログレスバーではない、13.3節の設計通り)。ログに「意図分類 ・ 開始」「実行中...」の行が即座に追加。
- done状態: 緑色のチェックマークに切り替わり、「event_lookup(LLM判定・検索要) ・ 2350ms」という要約が一度に表示。
- **メトリクスの実際の算出結果を確認**: 2ターン(42ms・2350ms)投入後、「直近の所要時間: 2350ms」「平均(直近2件): 1196ms」(=(42+2350)/2を四捨五入した値と一致)「即時判定: 1件」「LLM判定: 1件」と、正しく算出されていることを、画面上の実際の表示で確認した。
- ログが新しい順(開始→終了→開始→終了の逆順)に正しく並ぶことを確認した。
- ブラウザコンソール・ページエラーは、いずれのステップでも0件だった。

### 17.4 既存機能への非影響の確認

- バックエンドは1行も変更していないため、`backend/tests/`(16件)を実行し、変更前後で無影響であることを確認した(そもそも変更対象ではないため、当然の結果ではあるが、依頼書要件6への対応として明記する)。
- Live-2までのバックエンドテスト(`test_sigmaris_live_2_intent_classification_pilot.py`等)にも触れていない。

---

## 18. 気づいた懸念点・次のステップ(Live-4以降、他の処理への拡大)に向けた申し送り事項

1. **Live-1・Live-2から引き継がれた懸念(9〜11章)は、本タスクでは解消していない。** `invocation_id`が真の監査ログIDと一致しない問題(11章1点目)、複数ワーカー構成への非対応(同3点目)は、いずれもバックエンドの設計に関わるため、フロントエンドのみを対象とする本タスクの範囲外である。
2. **`resultSummary()`(live-process-flow.tsx)は、現時点で`intent_classification`専用の整形ロジックをハードコードしている。** `PROCESS_STEPS`配列自体は汎用化したが、「どのフィールドをどう要約表示するか」は処理ごとに異なりうる(例えば記憶検索なら`result_count`・`confidence_tier`等、意図分類とは全く違うフィールド)。次タスクで2つ目の処理を追加する際、この関数を`config.id`で分岐する形に拡張するか、各`ProcessStepConfig`に「要約整形関数」自体を持たせる(より汎用的だが、設定オブジェクトに関数を含める設計判断が必要)か、実際に2つ目の処理が追加された時点で決めるべきと考える——1つの処理しか無い現時点で、抽象化を先取りしすぎないことを優先した(判断根拠として明記)。
3. **メトリクスのサンプル数(20件)・キャッシュ等の永続化は行っていない。** ページを再読み込みすると、直近のイベント履歴・メトリクスは全て消える(Live-2から変わらない挙動)。長期的な推移を見たい場合は、Live-1、6.2節が示唆する範囲を超え、バックエンド側での履歴保存(例えば`/growth`ページと同様の、DBに記録された時系列データ)が必要になるが、これは「新しいデータ収集を追加しない」という依頼書2章3節の制約と両立しない可能性があり、慎重な検討が必要と考える。
4. **ナビゲーションへの正式な導線は、意図的に追加していない(page.tsxのコメントに判断根拠を明記済み)。** `AppShell`の`navItems`は固定5項目で、`/live`を追加するにはナビゲーション全体のレイアウト変更が必要になり、本タスクの範囲(`classify_chat_intent()`の表示のみ)を大きく超えると判断した。Sigmaris Liveが複数処理をカバーする、より恒久的な機能になった段階で、改めて検討する価値がある。
5. **観察者(Sigmaris Liveを見ている人)が、実際にチャットしている人と異なりうる、というLive-1、3.4節の想定に対し、本タスクのUIは特に何も配慮していない。** 現状は「今アクティブな1つの処理の状態」を表示するのみで、複数の会話が同時に進行した場合(例えば将来的に複数ユーザーが同時に使う場合)にイベントが混在して表示される可能性がある——`invocation_id`によるターンの区別自体はデータ上可能だが、UI側で「どのターンの一連の流れか」を視覚的に分離する設計は、本タスクでは行っていない(現状の単一ユーザー運用では実害が無いと判断し、優先度を下げた)。
6. **次タスクへの提案**: Live-1、6.2節の優先順位(応答生成→記憶検索→Evidence検索/ツール呼び出し)を踏襲しつつ、`PROCESS_STEPS`に次の処理を1件追加し、実際にフロー・メトリクス・ログの3つに自然に反映されることを確認しながら進めることを推奨する。特に応答生成(streaming)は、Live-1、6.2節が指摘した通り「演出ではなく本物のstreaming中継そのもの」という性質上、本タスクの`started`/`finished`二値モデルとは異なる表現(文字が実際に流れ込む速度そのものの可視化)が必要になる可能性が高く、`ProcessStepConfig`の設計を、この一様でない性質に対応できる形に拡張する必要が生じる可能性がある。
