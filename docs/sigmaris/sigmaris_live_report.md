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

---

# Sigmaris Live Live-4 実施報告: 他の処理への、イベント発行の、拡大

**作業ブランチ:** `sigmaris-live-4-process-expansion`(mainから新規作成)
**範囲:** Live-1が設計した、残りのトップレベルイベント(2.1節)のうち、記憶検索(`memory_search_*`)・応答生成(`response_generation_*`)・ツール呼び出し(`tool_call_*`)へ、イベント発行を拡大した。Evidence検索(`evidence_search_*`)は、20章1節で述べる理由により、本タスクの対象外とした。フロントエンドは、`PROCESS_STEPS`への追加と、Live-3の懸念点2(18章2点目)で申し送られていた課題への対応(結果要約ロジックの設定への移設)を行った。

## 19. 前提として確認したこと

着手前に、以下を実際のコードで確認した。

- `docs/sigmaris/sigmaris_live_report.md`(Live-1〜Live-3、1〜18章)。特にLive-1、2.1節(イベント一覧・発生源の行番号)・5章(リアルタイム性と演出の境界線)・6.2節(優先順位の初期提案)、Live-3、18章2点目(`resultSummary()`の`intent_classification`専用ハードコード問題)。
- `backend/app/services/orchestrator/service.py`: `_build_memory_context()`(当時741-873行目、現836-1006行目付近、B7〜B12・Temporal Layerの日記検索を内包)の戻り値が、単なる`str | None`であり、呼び出し元(2箇所)が検索件数・確信度層等の中間結果を一切受け取れない構造になっていることを確認した——イベントペイロード(2.2節設計)を組み立てるには、まずこの関数自体に戻り値の拡張が必要だと判明した。
- `backend/app/services/chat.py`の`stream_chat_completion_ui()`: `response_generation`に相当する`client.responses.create(..., stream=True)`のループ(当時`chat.py:1130-`)の開始・終了位置、および`execute_tool()`の呼び出し箇所(ツールごとに最大8回ループ内)を再確認した。
- `CONFIRMATION_REQUIRED_TOOLS`(`chat.py:54`付近): `create_google_calendar_events`・`create_app_events`・`delete_google_calendar_events`・`delete_google_calendar_events_in_range`・`save_travel_plan_for_event`の5種は、確認要求の分岐へ回され`execute_tool()`に到達しないことを確認した(21.3節のテストで、この分岐を踏まえたツール名選定が必要だった)。

## 20. 対象とした処理の一覧と、優先順位の判断根拠

### 20.1 今回拡大した処理と、見送った処理

| 処理 | 対応 | 判断根拠 |
|---|---|---|
| `memory_search_started`/`finished` | **実装した** | 依頼書が明示的に例示し、かつLive-1、6.2節が「次点で着手する価値が高い」と位置づけていた処理。`_build_memory_context()`という単一の関数の入出力を挟むだけで実現でき、影響範囲が閉じている。 |
| `response_generation_started`/`finished` | **実装した** | 既存のstreamingループ(BA4で確立済み)の開始・終了を挟むのみで、ループ内部のロジック(トークン中継・ツール呼び出し処理)には一切触れずに済む。依頼書が特に慎重な扱いを求めた処理だが、影響範囲を「ループの前後2行」に限定することで、リスクを最小化できると判断した。 |
| `tool_call_started`/`finished` | **実装した(判断根拠は独自追加)** | Live-1、2.1節の12種のイベントリストに元々含まれていた(#10)。応答生成ループを触るタイミングで、同じループ内にある`execute_tool()`呼び出しも合わせて計装する方が、同じ関数を2回に分けて変更するより差分が追いやすく、レビューコストも低いと判断し、今回まとめて対応した。 |
| `evidence_search_started`/`finished` | **見送った** | Live-1、2.1節・6.2節がいずれも「発生頻度が低い(条件付き)ため優先度が低い」と位置づけていた処理。今回は「リスクが低く価値の高いものから」という依頼書の方針に照らし、発生頻度が高く(=可視化の効用が大きい)、かつ影響範囲が閉じている3処理を優先した。次点候補として22章6点目に申し送る。 |
| `context_prepared_finished` / `request_started` / `request_finished` | **見送った** | Live-1、2.1節で設計はされているが、依頼書が「記憶検索・応答生成等」と名指しした処理ではなく、また`request_finished`は`OrchestratorStreamEvent(done=True)`という既存の完了シグナルと意味的に重複するため、今回の「他の処理への拡大」という主旨からは優先度が低いと判断した。 |

### 20.2 実装順序とリスクの考え方

依頼書「リスクが低く価値の高いものから順に拡大する」に対応し、以下の順序で実装・検証を進めた。

1. **記憶検索**: 影響範囲が`_build_memory_context()`という1関数の戻り値拡張+呼び出し元2箇所(非streaming・streaming)に閉じており、応答生成のような「ユーザーが直接体感する速度」に関わる箇所ではない(記憶検索はユーザーには元々不可視の処理)。最もリスクが低いと判断し、最初に着手した。
2. **応答生成**: 依頼書が「既存の応答速度に悪影響を与えないことを最優先すること」と明示的に強調した処理。記憶検索での実装・計測パターンが確立してから着手する方が、応答生成特有の懸念(ループ内でのオーバーヘッド蓄積等)に集中して検証できると考え、2番目にした。
3. **ツール呼び出し**: 応答生成のループ内に既にある処理であり、20.1節の通り同じ変更のまとまりとして対応するのが合理的だったため、応答生成と同時に実装した。

## 21. 各処理へのイベント発行の実装詳細

### 21.1 記憶検索(`memory_search_started`/`finished`)

`_build_memory_context()`(`orchestrator/service.py:833-`)自体は、既に検索件数・B7のクエリ分解有無・B11の確信度層・Temporal Layerの日記検索発火有無を、関数内部の局所変数として計算済みだった。**新しい計測ロジックは一切追加せず、既にある中間結果を、呼び出し元へ持ち帰るためだけの`@dataclass(frozen=True) class MemorySearchSummary`(`service.py:826-831`)を新設し、戻り値を`str | None`から`tuple[str | None, MemorySearchSummary]`へ変更した。**

呼び出し元は2箇所(`run_orchestrator_chat()`・`run_orchestrator_chat_stream()`)存在し、いずれも既に`invocation_id`(監査ログ用、`start_invocation()`が返す真のID)をこの時点で保持しているため、Live-2で申し送られていた「`chat.py`側は`message_id`しか持たない」という制約(11章1点目)には該当しない——記憶検索は`orchestrator/service.py`内で発生する処理であるため、最初から真の`invocation_id`をそのまま使える。

```python
_live_memory_search_started_at = time.perf_counter()
emit_live_event("memory_search_started", invocation_id)
profile_context, memory_search_summary = await _build_memory_context(
    jwt=jwt, user_id=user_id, messages=messages, fact_profile=fact_profile,
    fact_items=memory_context_fact_items, active_trends=active_trends,
    recent_topic_labels=_topic_labels_for_hint(current_topic, previous_topic),
    thread_id=effective_thread_id, threshold_adjustment=threshold_adjustment,
    entities=entities, relations=relations,
)
emit_live_event(
    "memory_search_finished", invocation_id,
    result_count=memory_search_summary.result_count,
    was_decomposed=memory_search_summary.was_decomposed,
    confidence_tier=memory_search_summary.confidence_tier,
    diary_search_triggered=memory_search_summary.diary_search_triggered,
    elapsed_ms=int((time.perf_counter() - _live_memory_search_started_at) * 1000),
)
```
(`run_orchestrator_chat()`側: `service.py:1397-1419`付近、`run_orchestrator_chat_stream()`側: `service.py:1694-1716`付近。2箇所は完全に同一パターン。)

**「演出禁止」の遵守(依頼書の最重要制約への対応)**: Live-1、5.2節が「記憶検索は、複数件の記憶が時間差で1件ずつ見つかるという実装にはそもそもなっていない(vector検索RPCが1回で一括して返す)」とコードで確認済みだったことを踏襲し、`started`と`finished`の二値のみを発行した。`finished`のペイロードにも、個々の記憶の内容や、件数の内訳を段階的に見せるような設計は一切含めていない——`result_count`(件数)・`was_decomposed`(分解の有無)・`confidence_tier`(確信度層のラベル)・`diary_search_triggered`(日記検索の発火有無)という、Live-1、2.2節がそのまま設計していた4フィールドのみを、追加の計測や演出なしにそのまま渡した。

### 21.2 応答生成(`response_generation_started`/`finished`)

`stream_chat_completion_ui()`(`chat.py`)内、応答生成の本体である`for _ in range(8):`ループの直前に`response_generation_started`を、ループを抜けた直後(フォールバック処理を含む、`chat.py:1368-1373`)に`response_generation_finished`を発行した。

```python
_live_response_generation_started_at = time.perf_counter()
emit_live_event("response_generation_started", message_id)

for _ in range(8):
    ...

emit_live_event(
    "response_generation_finished", message_id,
    response_length=len(final_text),
    elapsed_ms=int((time.perf_counter() - _live_response_generation_started_at) * 1000),
)
```

**「本物のリアルタイム表示」の実現方法についての判断根拠(依頼書の重要な制約への対応)**: 依頼書は「既存のストリーミング応答(BA4)の仕組みをそのまま活用し、本物のリアルタイム表示として実装すること」を求めていたが、Live-1、4.2節が既に「応答本文そのものは、外部観測用イベントに含めない」という、覆すべきでないプライバシー方針を確立していた。この2つの要求は、一見すると緊張関係にあるように見えたため、以下のように整理した。

- 応答本文そのものをLive側のイベントに載せる(=Live-1、4.2節の方針を覆す)ことはしない。本人向けの画面には、既存の`/api/agent/chat/stream`が既にトークン単位でstreamingしており、情報が失われるわけではない。
- 代わりに、「`_started`を受信してから`_finished`を受信するまでの実時間の長さそのもの」を、"本物のリアルタイム性"の表現とした。記憶検索・意図分類とは異なり、応答生成中は`active`状態が**実際にトークンが生成され続けている、正味の時間**だけ継続する(ループの前後を挟んだだけなので、疑似的な進捗表示を追加する余地がそもそも無い)。5.3節が提案していた「文字が実際に届いた分だけ画面に追記される」というタイピング風表示は、今回は実装していない(次項で理由を述べる)。
- **今回、文字送り表示までは実装しなかった判断根拠**: そのためには、`response_generation`用に新しいイベント種別(例: `response_generation_delta`、トークンが届くたびに発行)を追加する必要があるが、これは「既存のfire-and-forgetパターン・ペイロード設計をそのまま適用する」という依頼書の制約(=新しい設計をしない)と衝突する。既存の`classify_chat_intent()`のパターンは`started`/`finished`の二値のみであり、トークン単位の高頻度イベントという新しい種類の発行パターンは、依頼書が明示的に禁じた「新しい設計」に該当すると判断した。また、トークンごとに`emit_live_event()`を呼ぶと(23章の実測から)呼び出し回数が数十〜数百倍に増え、依頼書「既存の応答速度に悪影響を与えないことを最優先すること」との整合性を、まず`started`/`finished`の二値で安全に確認してから検討すべきと考えた。この点は22章6点目に次タスクへの申し送りとして明記する。

### 21.3 ツール呼び出し(`tool_call_started`/`finished`)

応答生成ループ内、`execute_tool()`の呼び出し(タイムアウト・`RefreshError`・その他例外のいずれの経路でも`tool_result`が確定した後に必ず`finished`を発行できるよう、`try/except`ブロック全体を`started`/`finished`で挟む形にした、`chat.py:1265-1315`付近)。

```python
_live_tool_call_started_at = time.perf_counter()
emit_live_event("tool_call_started", message_id, tool_name=function_call.name)
try:
    tool_result = await asyncio.wait_for(execute_tool(...), timeout=TOOL_EXECUTION_TIMEOUT_SECONDS)
except TimeoutError:
    ...
except RefreshError as error:
    ...
except Exception as error:
    ...
emit_live_event(
    "tool_call_finished", message_id,
    tool_name=function_call.name,
    ok=bool(tool_result.get("ok")),
    elapsed_ms=int((time.perf_counter() - _live_tool_call_started_at) * 1000),
)
```

`tool_name`・`ok`(成功可否)・`elapsed_ms`のみを含み、ツールの引数(位置情報・カレンダー内容等、Live-1、2.2節が既に「除外する情報」として明記していた項目)・実行結果の内容は一切含めていない。

### 21.4 非streaming経路(`run_chat_completion()`)には、引き続き手を加えていない

Live-2、7.2節の判断根拠1(streaming経路のみを対象とする)を、そのまま踏襲した。応答生成・ツール呼び出しの計装は`stream_chat_completion_ui()`にのみ行い、`run_chat_completion()`(WearOS等、非streaming用)には一切触れていない——Sigmaris Liveを見ながら使うという利用形態が想定されない経路を、対象範囲に含めない方針は、Live-2から一貫している。

## 22. フロントエンドの拡張は、設定の追加のみで実現できたか

### 22.1 検証結果: 部分的に「はい」——`computeStepStates()`は無変更、ただし結果要約ロジックの構造自体を1段深く汎用化する必要があった

**`computeStepStates()`(`process-steps.ts`)自体は、`memory_search`・`response_generation`を`PROCESS_STEPS`に追加した後も、1行も変更していない。** これはLive-3が設計した「イベント名・件数に依存しない汎用的な状態機械」という設計が、実際に機能したことの実証である。

一方、Live-3、18章2点目が申し送っていた通り、`resultSummary()`(旧`live-process-flow.tsx`)は`intent_classification`専用の整形ロジックをハードコードしており、これは「設定の追加のみ」では対応できなかった。今回、以下の2つの選択肢のうち、後者を選んだ。

- (a) `resultSummary()`を`config.id`で分岐する形に拡張する
- (b) **各`ProcessStepConfig`に、要約整形関数(`summarizeResult: (event: LiveEvent) => string`)自体を持たせる**

**判断根拠**: (a)は、処理が増えるたびに`live-process-flow.tsx`(表示コンポーネント)自身への変更が必要であり続け、「設定の追加のみで対応できる」という依頼書の要件を、根本的には満たせない(表示コンポーネントに手を加える点は変わらないため)。(b)は、表示コンポーネント(`live-process-flow.tsx`・`live-event-log.tsx`)を`config.summarizeResult(event)`を呼ぶだけの、真に汎用的なコードにできる——次に処理が増える際、`process-steps.ts`の`PROCESS_STEPS`配列にエントリを1つ追加するだけで、表示コンポーネントは本当に無変更のまま対応できる。Live-3時点でこの選択を先送りしていた判断(「1つの処理しか無い時点で抽象化を先取りしすぎない」)を、今回2つ目・3つ目の処理を追加する具体的な機会に、実際のニーズに基づいて解消した。

同様に、`LiveMetrics`(`live-metrics.tsx`)の「即時判定/LLM判定」カードも、旧実装は常に表示する前提だったが、この内訳(ヒューリスティック/LLM二択)は`intent_classification`固有の概念であり、記憶検索・応答生成には存在しない。`sourceBreakdownLabel?: { heuristic: string; llm: string }`という省略可能なフィールドを`ProcessStepConfig`に追加し、`LiveMetrics`側は`config.sourceBreakdownLabel`の有無だけで表示要否を判断する(`config.id`による分岐を持たせない)形にした。

### 22.2 `PROCESS_STEPS`に含めなかった処理: `tool_call`

`tool_call_started`/`finished`は、意図的に`PROCESS_STEPS`へ含めなかった。**判断根拠**: `PROCESS_STEPS`が前提とする状態機械(`computeStepStates()`)は、「1ターンにつき、その処理は高々1回しか発生しない」ことを暗黙の前提にしている(`started`受信で`active`、`finished`受信で`done`という単純な二値遷移)。`tool_call`は1ターンに0〜複数回発生しうる、性質の異なるイベントである。これを無理に`PROCESS_STEPS`へ含めると、複数回のツール呼び出しのうち最後の1回しか状態に反映されない、という誤った単純化になる。そのため、ログ(`live-event-log.tsx`)・メトリクス(`metrics.ts`の`computeToolCallMetrics()`)には個別に対応する専用ロジックを追加したが、「処理の流れ」(`LiveProcessFlow`)には表示しない設計とした。この判断はLive-1〜3で明示的に議論されていなかった、本タスクで新たに直面した設計判断であるため、独自の判断根拠として明記する。

### 22.3 結論

「設定の追加のみで新しい処理に対応できる」という依頼書の設計目標は、**`computeStepStates()`という状態遷移ロジックに関しては完全に実証された**が、**表示・整形ロジックに関しては、Live-3時点の実装ではまだ「設定の追加のみ」になっておらず、本タスクでその構造自体を`summarizeResult`/`sourceBreakdownLabel`という形でconfigへ移す追加のリファクタリングが必要だった**、というのが正直な検証結果である。このリファクタリングを経た後の現状であれば、次(4つ目)の処理を追加する際は、真に`process-steps.ts`への追加のみで、表示コンポーネント側は無変更のまま対応できると考える。

## 23. 応答速度への影響の確認結果

Live-2、9章と同じ方法(実装した`emit_live_event()`そのものを直接計測)で、今回追加した3処理分(記憶検索・応答生成・ツール呼び出し、計6回のイベント発行/ターン)を含めて再計測した。

```
2000イテレーション × 6回/イテレーション(観察者接続なし):
  1回あたり平均 3.82マイクロ秒

同条件、観察者(SSE購読者)が1つ接続された状態:
  1回あたり平均 4.44マイクロ秒
```

Live-2の実測(意図分類のみ、2回/イテレーション、6.79〜7.24マイクロ秒/回)と比べ、イベント発行回数が3倍(2回→6回/ターン)に増えたにもかかわらず、1回あたりのオーバーヘッドは同じマイクロ秒オーダーに留まっており、悪化していない。応答生成(`for _ in range(8):`ループ、数百ミリ秒〜数秒かかりうる処理)に対し、追加した2回分の`emit_live_event()`呼び出し(合計1桁マイクロ秒)は、測定不能なほど小さい。

また、キューが枯渇した場合の`"live_events: subscriber queue full, dropping event"`警告(Live-2、9章末尾で確認済みの既知の挙動)も、今回のベンチマーク(観察者側でキューを消費しない条件)で同様に観測されたが、これはイベント量が3倍になったことによる新しい問題ではなく、既存の既知の挙動がそのまま再現しただけであることを確認した。

**実モデルAPIでの計測は、依頼書の制約により行っていない**(`OPENAI_API_KEY`が利用できない環境のため)。応答生成ループ自体は全てモックであり、実際のトークン生成速度への影響(理論上ゼロのはずだが)は、本番環境での実測を推奨する(25章5点目)。

## 24. テスト結果

### 24.1 バックエンド

`test_sigmaris_live_4_expansion.py`に7件のテストを新設した(スクラッチディレクトリ、リポジトリには追加していない——Live-1〜3までの前例と同じ扱い)。

- `BuildMemoryContextSummaryTests`(3件): `_build_memory_context()`の新しいタプル戻り値が、様々なモック状況(結果あり・ユーザーテキストなし・日記検索発火)で、`result_count`/`was_decomposed`/`confidence_tier`/`diary_search_triggered`を正しく反映することを確認。
- `OrchestratorMemorySearchEventTests`(1件): `run_orchestrator_chat()`実行時、`memory_search_started`/`finished`が正しい順序・ペイロードで発行されることを確認。
- `ChatStreamResponseGenerationEventTests`(2件): `response_generation_started`/`finished`が、streamingループ全体を正しく挟み、`response_length`が正しいこと、および**発行された、いずれのイベントのペイロードにも、応答本文が一切含まれないこと**(プライバシー確認)を検証。`tool_call_started`/`finished`についても、`tool_name`/`ok`が正しいこと、ツール引数に含めた模擬的な機密情報(`"秘密の住所123"`)が、いずれのイベントペイロードにも漏れていないことを検証。
- `LiveEventBusFailureResilienceTests`(1件): `LiveEventBus.publish()`が例外を送出するよう細工した状態でも、`stream_chat_completion_ui()`が正常に完了することを確認(Live-2と同じ検証方法論——`emit_live_event()`自体をモックするのではなく、実際のバスの`publish()`をモックする方が実態に忠実と判断)。

既存テストとあわせて、`backend/tests/`の16件全てが成功した(回帰なし)。`_build_memory_context()`の戻り値をタプルに変更したことに伴い、`test_service.py`の既存モック(`AsyncMock(return_value="memory")`)を`AsyncMock(return_value=("memory", MemorySearchSummary()))`に修正する必要があったが、これは戻り値の形状変更に伴う機械的な追随であり、テストの意図(`_build_memory_context()`の呼び出しをモックして`run_orchestrator_chat*()`の他の挙動を検証する)自体は変えていない。

### 24.2 フロントエンド

```
npx eslint src/components/live src/app/live   → エラーなし
npx tsc --noEmit(フロントエンド全体)          → エラーなし
npx next build                                → 成功(全42ルート、/live・/api/live/streamを含む)
```

### 24.3 実際にブラウザを起動しての動作確認(Live-3、17.3節と同じ手法)

Live-3と同じく、コミットしない一時的な確認用ルート(`live-preview-test-noauth`)経由で`LiveDashboard`を表示し、`window.EventSource`をフェイク実装に差し替え、Playwright(`chromium`ヘッドレス)でスクリーンショットを取得した。今回は2ターン分(意図分類→記憶検索→応答生成+ツール呼び出し1回、を2回)を模擬発行し、以下を確認した。

- **idle→active→doneの状態遷移**: 記憶検索・応答生成のいずれも、`_started`受信時にスピナー(パルスする紫の円)へ、`_finished`受信時に緑のチェックマーク+要約表示へ、正しく切り替わることをスクリーンショットで確認。応答生成が`active`である間、他の完了済みステップ(意図分類・記憶検索)は`done`のまま維持されることも確認した。
- **結果要約の内容**: 記憶検索は「記憶3件(確信あり)・複数の観点に分解 ・ 187ms」、応答生成は「128文字を生成 ・ 932ms」のように、22.1節で設計した`summarizeResult()`が、日本語の読みやすいラベルへ正しく変換して表示することを確認した。
- **メトリクス**: 2ターン分投入後、意図分類・記憶検索・応答生成それぞれの直近値・平均値(直近2件)、およびツール実行の件数・成功・失敗件数(2件中、成功1件・失敗1件)が、正しく算出されて表示されることを確認した。
- **ログ**: 16件のイベント(2ターン×8イベント)が新しい順に、処理ごとの要約とともに正しく表示されることを確認した。ツール呼び出しの成功/失敗ラベルも正しく区別されていた。
- **コンソールエラー・ページエラー**: いずれのステップでも0件だった。
- 確認用の一時ルート・検証スクリプトは、検証後にすべて削除し、`git status`で作業ツリーがLive-4本来の変更のみになっていることを確認した(削除に伴い発生した、Next.jsの型キャッシュ(`.next/dev/types/validator.ts`)が削除済みルートを参照し続ける問題は、`.next`ディレクトリを削除して`tsc --noEmit`を再実行することで解消し、再度エラーなしを確認した)。

### 24.4 line-ending(改行コード)混入の検出・修正

編集作業の過程で、`backend/app/services/orchestrator/service.py`(既存ファイルがCRLF/LF混在)が、Editツールによる編集を経て、ファイル全体がLFのみに変換されてしまう、Self-3等で既知の問題が今回も発生した(`git diff`が2291行の変更として表示される一方、`git diff --ignore-cr-at-eol`では69行のみで、実質的な変更は69行分に過ぎないことを確認して発覚)。既存の対処パターン(pristineな`git show HEAD:`の内容を基準に、変更が無い行は元の改行コードを維持したまま、差分のある行のみ新しい内容で置き換える)を適用し、`git diff`と`git diff --ignore-cr-at-eol`の行数が69行で一致することを確認して修正した。`backend/app/services/chat.py`側では、この問題は発生していなかった(33行で両者が最初から一致)。

## 25. 気づいた懸念点・次のステップに向けた申し送り事項

1. **応答生成の「文字送り表示」は、今回実装していない(21.2節)。** `started`/`finished`の二値モデルでは、`active`状態の継続時間が実時間を正しく反映するが、生成された文字が実際に画面に流れ込む様子までは可視化できていない。トークン単位の高頻度イベント(例: `response_generation_delta`)を追加検討する場合、既存の`classify_chat_intent()`パターン(二値のみ)から意図的に逸脱する新しい設計判断になるため、次タスクでは、まず本タスクの二値モデルを実運用でしばらく観察し、応答生成の`active`状態の継続時間表示だけで十分な価値があるかを確認してから、要否を判断することを推奨する。
2. **Evidence検索(`evidence_search_*`)は、今回も見送った(20.1節)。** Live-1、6.2節・本タスクの20.1節がいずれも優先度を低く位置づけている通り、発生頻度が低い(条件付き)処理であるため、次に拡大する候補として妥当だが、まだ着手していない。
3. **`invocation_id`と`message_id`の不一致(Live-2、11章1点目)は、記憶検索・ツール呼び出し・応答生成のいずれの新規イベントでも未解消のまま。** 記憶検索(`orchestrator/service.py`側)は真の`invocation_id`を使えているが、応答生成・ツール呼び出し(`chat.py`側)は引き続き`message_id`を使っている(Live-2からの既存の制約をそのまま継承)。現状、フロントエンドの`computeStepStates()`はイベント種別のみで状態を判定し、`invocation_id`によるターンの相関は行っていないため、実害はないが、将来「同時に複数ターンが進行した場合に、どのターンの記憶検索が、どのターンの応答生成に対応するか」を区別する必要が生じた場合には、この不一致の解消(Live-2、11章1点目が示す`X-Correlation-ID`の受け渡し)が前提になる。
4. **`tool_call`を`PROCESS_STEPS`に含めない、という設計判断(22.2節)は、次に「1ターンに複数回発生しうる処理」を追加する際の先例になる。** 現状はログ・メトリクスへの個別対応のみだが、将来この種の処理が増えた場合、ログ・メトリクス双方に同種の対応を都度追加するのではなく、共通の抽象化(例えば「多重発生イベント」というもう1つのカテゴリ)を検討する価値が出てくる可能性がある。1種類しか無い現時点では、抽象化を先取りしないことを優先した。
5. **実モデルAPIでの検証は、依頼書の制約により行っていない(23章末尾)。** 応答生成・ツール呼び出しの計装が、実際のOpenAI API呼び出し・実際のツール実行の所要時間そのものに与える影響(理論上、追加した`emit_live_event()`呼び出し2〜4回分のマイクロ秒オーダーのみのはず)は、本番環境での実測を推奨する。
6. **次タスクへの提案**: 22.1節で確立した`summarizeResult`/`sourceBreakdownLabel`という、真に設定追加のみで拡張できるフロントエンド設計を活かし、Evidence検索(`evidence_search_*`、上記2点目)、または応答生成の文字送り表示(上記1点目)のいずれかへ拡大することを推奨する。後者に着手する場合は、まず本タスクの実測(23章)を上回るイベント発行頻度になることを踏まえ、オーバーヘッドの再計測を必須の検証項目に含めるべきである。

---

# Sigmaris Live Live-5 実施報告: 詳細表示、+機密情報のマスキング

**作業ブランチ:** `sigmaris-live-5-detail-masking`(mainから新規作成)
**範囲:** Live-4までで実装した要約データのみの表示(意図分類・記憶検索・応答生成・ツール呼び出し)に加え、記憶検索・ツール呼び出しの各ログ行をクリックすると、マスキング済みの詳細情報が展開表示される機能を追加した。応答生成の詳細表示は、後述する理由により実装していない。

## 26. 着手前の調査で判明した、アーキテクチャ上の分岐点(実装着手前に一度立ち止まった経緯)

依頼書は「プライバシーに関する判断に迷う場合は、必ず実装を止めて、報告すること」を繰り返し強調していたため、実装に着手する前に、まず「詳細情報をどこから、どう取得するか」を調査した。判明した事実は以下の通りである。

1. **記憶の生の内容・ツール引数の値は、現状どこにも永続化されていない。** `agent_invocation_audit_logs`(`audit.py`)の`request_summary`/`response_summary`も、既にメッセージ件数・ガード違反等の要約データのみで、記憶内容やツール引数を保持していない。つまり「詳細表示」を実現するには、何らかの新しいデータ永続化が必要だった。
2. **`/api/agent/live/stream`(既存)の認証設計は、「配信データが要約データのみであること」を前提に、ユーザーJWTを要求しないという判断を、明示的なコメントとして残していた**(`routes/agent.py`、663-670行目)。詳細情報(マスキング済みとはいえ、記憶検索・ツール呼び出しのより個人的な内容)を、既存のSSEイベントへそのまま追加すると、この前提そのものを壊すことになる。

この2点から、「詳細情報の実現方法」自体が、Live-1、4.3節が既に想定していた分岐点(「詳細情報は、エージェント認証に加え、本人のJWTによる確認も必須にすべき」)に直接該当すると判断し、実装を進める前に、海星さんへ選択肢を提示して確認を求めた。提示した選択肢は、(a)新規のJWT認証必須な詳細取得エンドポイントを実装する、(b)既存のSSEペイロード自体を拡張する、(c)マスキング基盤・UIのみを実装しデータソースは後回しにする、(d)ここで止めて報告のみに留める、の4つで、**(a)が選択された。** 以下は、(a)の実装内容である。

## 27. マスキングの実装詳細(検出方法、判断根拠)

### 27.1 新設モジュール: `backend/app/services/live_detail_masking.py`

**既存の`x_privacy_filter.py::filter_private_info()`を、そのまま流用しなかった判断根拠**: 同関数は、X投稿という公開の場でのチェックであり、都道府県・市区町村レベルの地名や、ありふれた個人名は、意図的にブロック対象外としている(同モジュールのdocstringに明記)。Sigmaris Liveの詳細表示は、記憶検索・ツール呼び出しという、より個人的な内容(家庭の出来事・予定等)を扱うため、同じ判定基準を流用せず、地名・氏名・日付も対象に含む、独自の、より安全側に倒したマスキングを実装した。ただし、regex-onlyで実装する(LLM呼び出しを行わない)という設計方針自体は、同モジュールの「マスキング対象の判定のためだけに、ユーザーの内容を外部LLM APIへ送信することは、プライバシー方針そのものに反する」という考え方を、そのまま踏襲した。

`mask_sensitive_text(text) -> (masked, any_masked)`が、以下のパターンを検出し、`[マスク済み]`へ置換する。

| 種別 | 例 | 備考 |
|---|---|---|
| 日付 | `7月3日`, `2026-07-18` | 個別の出来事に紐づきうる具体的な日付 |
| 地名 | `渋谷区`, `新宿駅` | x_privacy_filter.pyより広く、市区町村・駅名の単位も対象 |
| 氏名(敬称付き) | `田中さん`, `太郎くん` | 敬称の直前の1〜10文字を氏名と推定 |
| メール・電話・信用情報・IP・金額・番地 | — | x_privacy_filter.pyと同種のパターンを、独立して定義 |

**テスト中に発見した既存パターンの潜在的な不具合**: `x_privacy_filter.py`の電話番号・IPアドレスパターンは末尾を`\b`(単語境界)で終端しているが、日本語の文章では、数字の直後に助詞等の(Unicode上は`\w`と判定される)文字が空白無しで続くことが多く、`\b`は「数字→日本語文字」の境界を検出できない(どちらも`\w`と判定されるため境界と見なされない)。実際に`test_masks_phone`(「電話番号は090-1234-5678です」)で検出漏れが発生し、初めて気づいた。本タスクの`live_detail_masking.py`では、該当パターンの終端を`(?!\d)`(直後が数字でないことを確認する先読み)に変更して修正した。**`x_privacy_filter.py`側の同名パターンは、X投稿という別の用途で使われており、本タスクの範囲外のため変更していない**——ただし、日本語文が直後に続く場面(ツイート本文中の電話番号等)では、同種の検出漏れが起きうることを、次のステップへの申し送りとして28章に明記する。

### 27.2 記憶検索の詳細: 何を見せ、何を見せないか

依頼書は「検索クエリ・ヒットした記憶の件数は表示してよい」としていたが、**検索クエリ自体(=ユーザーの直近の発言)は、詳細表示にも一切含めないという判断をした。** 判断根拠: Live-1、4.1節は「ユーザーの発言内容そのもの」を、全イベント共通の除外項目として明記しており、Evidence検索についても「検索クエリ文字列」を明示的に除外情報としていた(2.2節の表)。記憶検索の「クエリ」は、実質的にユーザー自身の発言そのものであり、これをマスキングした上で見せたとしても、文の構造・意図の大部分は残ってしまう——依頼書の「検索クエリは表示してよい」という一文と、Live-1が既に確立していた、より基本的な原則が、文面上は緊張関係にあったため、後者を優先する、安全側の解釈を採用した。

代わりに、`_build_memory_context()`(`orchestrator/service.py:833-`)が既に計算済みの、ヒットした記憶それぞれについて、以下を`MemorySearchSummary.masked_detail`(同、828-838行目)へ含めた。

```python
{
    "category": item.get("category") or "",
    "value_preview": build_masked_memory_preview(str(item.get("value") or ""))[0],
    "confidence": item.get("confidence"),
    "similarity": item.get("similarity"),
}
```

`value_preview`は、`mask_sensitive_text()`でマスキングした後、160文字に切り詰めたものである(マスキングを先に行う理由: 切り詰めを先に行うと、パターンが文字数の境界で分断され、検出漏れが増える可能性があるため)。`category`・`confidence`・`similarity`は、既存の`memory_search_finished`要約イベント(Live-4)と同じ、構造的な情報としてそのまま含めている。

### 27.3 ツール呼び出しの詳細: 引数は「種類」のみ表示し、値は原則すべてマスキングする

依頼書は「引数の種類は表示してよいが、値に個人情報が含まれる可能性がある場合はマスキングする」としていたが、**このアプリのツール引数(カレンダー予定・旅行計画等)は、ほぼ全てが自由記述(タイトル・場所・メモ等)であり、regexによる部分マスキングでは、文の構造や意図がそのまま残ってしまい、見逃しのリスクが高いと判断した。** そのため、`mask_tool_arguments()`(`live_detail_masking.py`)は、文字列値を【原則すべて】`[マスク済み]`に置換し、数値・真偽値・null(構造的な情報であり、内容そのものではない)のみ、そのまま表示する、という、より単純で安全側に倒した方針にした。list/dict等のネストした構造も、自由記述を含みうるため、丸ごとマスキングする。

これにより、「どんな種類の引数を渡したか」(キー名)は見えるが、値そのものはほぼ常にマスキングされる——依頼書の「明らかに機密性が高い可能性のある情報は安全側に倒して隠す」という方針を、記憶検索よりもさらに一段厳しく適用した形である。

### 27.4 「マスキングされている」ことの明示方法(誠実さについての設計判断)

依頼書3章「何も隠していないかのように見せることを避ける」への対応として、詳細表示パネル(`live-event-detail-panel.tsx`)は、二段構成の注記を実装した。

1. **常時表示する、一般的な注記**: 「この詳細表示は、機密性の高い可能性のある情報を検出した場合にマスキングして表示します。検出は簡易的なもので、完全ではありません。」——実際にマスキングが発生したかどうかに関わらず、常に表示する。
2. **実際にマスキングが発生した場合のみ表示する、個別の注記**: 「この項目には、マスキングされた箇所(`[マスク済み]`)が含まれています。」——`masked_detail.any_masked`が`true`の場合のみ、目立つ配色(amber系)で表示する。

1のみでは「今回はマスキングされていない」という誤解を与えうるため、2を出し分けることで、実際の発生有無を正直に伝える設計にした。

## 28. 実装詳細(データの流れ)

### 28.1 新規テーブル: `sigmaris_live_event_details`(マイグレーションのみ作成、未適用)

`supabase/migrations/202608080066_live_event_details.sql`。`agent_invocation_audit_logs`と同じ、`user_id`列+行レベルセキュリティ(`auth.uid() = user_id`、select/insertのみ、update/deleteは無し=書き込み専用ログ)のパターンを踏襲した。既存テーブルへdetail列を追加する案ではなく独立テーブルにした理由: `tool_call`は1ターンに0〜複数回発生しうる(Live-4で既に確立した設計)ため、`detail_key`(記憶検索は`invocation_id`、ツール呼び出しは`tool_call_id`)単位で複数行を持てる構造が必要だった。依頼書の指示通り、**マイグレーションの適用(実際のDB反映)は行っていない**——運用者の判断に委ねる。

### 28.2 永続化: `backend/app/services/live_event_details.py`

`emit_live_event()`と同じfire-and-forgetパターン(`asyncio.create_task()`のみ、内部でtry/exceptして例外を外へ伝播しない)を踏襲しつつ、2種類のエントリポイントを用意した。

- `persist_live_event_detail_bg(jwt, user_id, ...)`: 呼び出し元が既に`user_id`を持っている場合用(`orchestrator/service.py`側)。
- `persist_live_event_detail_bg_from_jwt(jwt, ...)`: `user_id`を持たない呼び出し元用(`chat.py`側)。fire-and-forgetタスクの内部で`get_current_user(jwt)`を呼んでから`rest_insert()`する——この追加のSupabase Auth呼び出し(通常数十ms)は、タスク全体が非同期でバックグラウンド実行されるため、応答ストリームを一切ブロックしない。

**なぜ`chat.py`側は`user_id`を持たないか**: `stream_chat_completion_ui()`は、HTTPホップ(`agent_chat_stream()`)経由で呼ばれ、`jwt`のみを受け取り、`user_id`を引き継いでいない——Live-2、11章1点目で既に文書化済みの、`invocation_id`/`message_id`の不一致と、全く同じ構造的な制約である。新しいパラメータを追加してこの制約を解消することも検討したが、共有ホットパスへの変更になるため、Live-2の判断根拠1に倣い、今回は見送った(fire-and-forgetタスク内での`get_current_user()`呼び出しで十分に対処できたため)。

### 28.3 呼び出し箇所

- **記憶検索**(`orchestrator/service.py:1460-1467`、`:1767-1774`、2箇所とも同一パターン): `memory_search_finished`のemit_live_event直後、`memory_search_summary.masked_detail["items"]`が空でない場合のみ、`persist_live_event_detail_bg()`を呼ぶ(不要なDB書き込みを避けるため、記憶がヒットしなかったターンでは永続化自体をスキップする)。
- **ツール呼び出し**(`chat.py`): `tool_call_finished`のemit_live_event直後、`mask_tool_arguments(arguments)`でマスキングした引数を、`persist_live_event_detail_bg_from_jwt()`で永続化する。`detail_key`には、Live-4で既に`_build_tool_ui_part()`向けに計算済みだった`tool_call_id`(`function_call.call_id`またはフォールバックのuuid)を使う——`message_id`だけでは、1ターン中に同じツールが複数回呼ばれた場合に、どの呼び出しの詳細か区別できないため、`tool_call_started`/`tool_call_finished`イベント自体にも`tool_call_id`フィールドを追加した(Live-4時点では未発行だった)。

### 28.4 詳細取得エンドポイント

- **バックエンド**: `GET /api/agent/live/detail`(`routes/agent.py`)。`_verify_agent()`に加え、`_require_jwt()`も必須にした——Live-1、4.3節の設計方針をそのまま実装し、`/live/stream`が「要約データのみだから」という前提でJWTを省略しているのに対し、本エンドポイントは意図的に非対称な、より厳格な認証にしている。`event_type`は`memory_search_finished`/`tool_call_finished`の2値のみ許可し、それ以外は400を返す。取得した`jwt`をそのまま`get_live_event_detail()`経由でSupabase RESTへ転送するため、行レベルセキュリティが、実際にリクエストしたユーザー本人の権限でのみ適用される(サービスロールで全ユーザー分を横断的に読めるような実装にはしていない)。
- **フロントエンド**: `frontend/src/app/api/live/detail/route.ts`(新設)。`/live/stream`用の`readAgentHeaders()`(エージェント認証、環境変数)に加え、`createClient()`(Supabaseサーバーサイドクライアント)で取得した、閲覧中の海星さん本人のセッション(`access_token`)も、`Authorization: Bearer`ヘッダとしてバックエンドへ転送する。
- **UI**: `live-event-detail-panel.tsx`(新設)。ログの行(`live-event-log.tsx`)のうち、`memory_search_finished`/`tool_call_finished`の行のみクリック可能にし(`detailLookupFor()`が対象外と判断した行は、クリックしても何も起きない)、クリックで`/api/live/detail`を取得し、展開表示する。

## 29. フロントエンドの拡張は、設定の追加のみで実現できたか

本タスクは、Live-4までで確立した`PROCESS_STEPS`config配列とは別の、新しい種類の拡張(行クリックでの詳細表示)であるため、既存のconfig配列自体への追加だけでは完結しなかった——新しいコンポーネント(`live-event-detail-panel.tsx`)と、新しいAPIエンドポイントの追加が必要だった。ただし、既存の3コンポーネント(`LiveProcessFlow`・`LiveMetrics`・`LiveEventLog`のうち前2つ)には一切手を加えておらず、`LiveEventLog`への変更も、行のクリックハンドラと、展開時に子コンポーネントを差し込むだけの、局所的な追加に留めている。`detailLookupFor()`が「この処理には詳細表示がある」という判定を一箇所に集約しているため、将来3つ目の詳細表示対象(例えばEvidence検索が追加された場合)は、この関数へ1分岐追加するだけで対応できる設計にした。

## 30. 応答速度への影響の確認結果

### 30.1 マスキング自体のオーバーヘッド

`mask_sensitive_text()`は、9個のregexパターンを直列に適用するのみ(LLM呼び出し無し)。記憶検索の`_build_memory_context()`は、既に数百ミリ秒〜数秒かかりうる処理(B7のクエリ分解等)であり、そこへ数件の記憶それぞれに対する、短い文字列(数百文字以下)への regex 適用が追加されるのみで、実行時間への影響は測定するまでもなく無視できるレベルと判断した(Live-2〜4のマイクロ秒オーダーのベンチマークと同種の性質)。

### 30.2 永続化(DB書き込み)のオーバーヘッド

`persist_live_event_detail_bg()`/`persist_live_event_detail_bg_from_jwt()`は、いずれもfire-and-forget(`asyncio.create_task()`のみ)であるため、Supabase RESTへの実際のHTTP書き込み(数十〜数百ミリ秒かかりうる)は、応答ストリームの完了を一切待たない。これはLive-2〜4の`emit_live_event()`(インメモリのみ、I/O無し)より重い処理を、初めて同じfire-and-forgetパターンに乗せた事例である——**実モデルAPIでの実測は依頼書の制約により行っていないが、この設計自体は、応答速度への影響が理論上ゼロになるよう意図されている**(点火して待たない、失敗しても握りつぶす、という2点は、実行時間の長さに関わらず成立する)。次ステップとして、本番環境での実測(fire-and-forgetタスクが実際に完了するまでの時間、および`sigmaris_live_event_details`テーブルへの書き込み頻度)を推奨する。

## 31. テスト結果

`test_sigmaris_live_5_detail_masking.py`に24件のテストを新設した(スクラッチディレクトリ、リポジトリには追加していない)。

- **マスキングロジック(10件)**: 日付・地名・氏名(敬称付き)・メール・電話番号の検出、一般的な文章での誤検出が無いこと、160文字切り詰め、ツール引数の文字列値が全てマスキングされること・数値/真偽値/nullは通過すること・ネスト構造もマスキングされること・生のPII(テスト用の模擬機密情報「秘密の住所123」)がマスキング後の出力に一切残らないこと。
- **`_build_memory_context()`統合(2件)**: 検索結果(日付・地名・氏名を含む模擬データ)から、`MemorySearchSummary.masked_detail`が、マスキング済みプレビューを正しく含むこと・生の値が一切残っていないこと・結果0件の場合は空のitemsになること。
- **永続化(6件)**: `persist_live_event_detail_bg()`が正しいペイロードで`rest_insert()`を呼ぶこと・失敗しても例外が外へ伝播しないこと・`persist_live_event_detail_bg_from_jwt()`が`get_current_user()`経由で`user_id`を解決してから挿入すること・`user_id`が解決できない場合は挿入自体をスキップすること・`get_live_event_detail()`が該当行が無い場合`None`を返すこと・最新1件の`masked_detail`を正しく返すこと。
- **エンドポイント認証(4件)**: `_verify_agent()`が無い場合401・`_require_jwt()`が無い場合401・未対応の`event_type`は400・正しいリクエストは`get_live_event_detail()`を正しい引数(ユーザーのjwt・event_type・key)で呼ぶこと。

既存テストとあわせて、`backend/tests/`の16件全てが成功した(回帰なし)。`import app.main`もクリーンに成功することを確認した。

フロントエンドは以下を確認した。

```
npx eslint src/components/live src/app/live src/app/api/live   → エラーなし
npx tsc --noEmit(フロントエンド全体)                             → エラーなし
npx next build                                                   → 成功(/api/live/detailを含む全43ルート)
```

### 31.1 実際にブラウザを起動しての動作確認(Live-3〜4と同じ手法)

コミットしない一時的な確認用ルート経由で`LiveDashboard`を表示し、`window.EventSource`に加え、今回は`window.fetch`の`/api/live/detail`宛リクエストのみをフェイク応答に差し替え(実際のバックエンド・Supabaseセッションが無い環境でも、UIの見た目を検証するため)、Playwright(`chromium`ヘッドレス)でスクリーンショットを取得した。

確認できたこと:
- 記憶検索・ツール呼び出しの行はクリックすると詳細パネルが展開され、クリックできない行(意図分類等)はクリックしても何も起きないこと。
- 記憶検索の詳細に、マスキング済みプレビュー(`[マスク済み]に[マスク済み]と会った`)がカテゴリ・confidence・similarityとともに表示されること。
- ツール呼び出しの詳細に、引数のキー名(`title`・`location`・`all_day`・`duration_minutes`)が表示され、文字列値のみ`[マスク済み]`に、数値・真偽値はそのまま表示されること。
- マスキングが発生した場合、amber系の個別注記が表示され、常時表示の一般的な注記(グレー、下部)とあわせて二段で表示されること。
- 再クリックで詳細パネルが正しく折りたたまれること(トグル動作)。
- ブラウザコンソール・ページエラーは、いずれのステップでも0件だった。
- 確認用の一時ルート・検証スクリプトは、検証後にすべて削除し、`git status`で作業ツリーが本タスク本来の変更のみになっていることを確認した。

### 31.2 line-ending混入の検出・修正

今回も、`orchestrator/service.py`への編集で、既知のCRLF/LF混在ファイルの全体LF化が発生した(`git diff`が2280行、`git diff --ignore-cr-at-eol`では60行)。既存の対処パターン(difflibで新旧の行内容を比較し、内容が同じ行は元の改行コードを維持、変更/追加行のみ新しい内容にする)で修正し、60行で両者が一致することを確認した。`chat.py`・`routes/agent.py`は、いずれも変更前後で行数が一致しており、この問題は発生しなかった。

## 32. 気づいた懸念点・次のステップに向けた申し送り事項

1. **`sigmaris_live_event_details`テーブルの保持期間(retention)ポリシーは、未実装。** マスキング済みとはいえ、ユーザーの記憶・予定に由来する内容を含むテーブルであるため、自動削除の仕組み(cronによるパージ等)を、運用者が必要に応じて追加することを推奨する(マイグレーションのコメントにも明記済み)。
2. **マスキングは、完璧ではない(依頼書自身が許容している通り)。** 特に氏名検出は、敬称(さん・くん・様等)が付いている場合のみ検出でき、敬称の無い固有名詞(例えば「まさし」のような、文脈でしか判断できない名前)は検出できない。地名も、パターンに一致しない表現(俗称・略称等)は素通りする。この限界は、詳細パネルの常時注記(27.4節)で正直に伝えているが、記憶の内容によっては、依然として個人が特定できる情報が残る可能性がある——運用しながら、実際に見逃されたパターンを継続的に拾い上げ、regexを育てていく運用が必要になると考える。
3. **`x_privacy_filter.py`の電話番号・IPアドレスパターンにも、同種の`\b`検出漏れが潜在する可能性がある(27.1節)。** 本タスクでは`live_detail_masking.py`側のみ修正し、`x_privacy_filter.py`自体は本タスクの範囲外として変更していない。X投稿本文で、電話番号等の直後に空白無しで日本語が続くケースがどの程度あるか、次のステップで確認する価値がある。
4. **応答生成の詳細表示は、今回実装していない(依頼書「別途慎重な検討が必要、判断に迷う場合は実装せず報告すること」への対応)。** Live-4が既に「応答本文はイベントに含めない」という設計を確立しており、本タスクでもこの方針を維持した。将来、応答生成の詳細表示が必要になった場合、他の2処理と異なり、応答本文そのものの扱いについて、改めて独立した検討(そして、必要であれば海星さんへの確認)が必要になる。
5. **`tool_call_id`の追加(28.3節)により、Live-4のイベントペイロードが変わった**(`tool_call_started`/`finished`に`tool_call_id`フィールドが追加された)。既存のLive-4フロントエンドコード(`toolCallSummary()`等)は、このフィールドを参照していないため後方互換だが、今後Live-4のイベント形式に依存する新しいコードを書く際は、この追加フィールドの存在を前提にしてよい。
6. **次タスクへの提案**: 29章で述べた`detailLookupFor()`の拡張ポイントを活かし、Evidence検索等、新しい処理が追加された際に、同じ「詳細表示」パターンを再利用できるかを検証することを推奨する。また、1点目の保持期間ポリシーは、機能追加ではなく運用上の懸念であるため、実際の運用開始前に、運用者の判断を仰ぐことを強く推奨する。

---

# Sigmaris Live Live-7 実施報告: デモモード(X発信・動画撮影用の、模擬データ)

**作業ブランチ:** `sigmaris-live-7-demo-mode`(mainから新規作成)
**範囲:** X発信・動画撮影用に、個人情報を一切含まない架空のシナリオを、実際のSSE接続の代わりに再生する「デモモード」を追加した。バックエンドの変更は一切無い(フロントエンドのみのタスク)。

## 33. デモモードの切り替え方法

`/live?demo=1`(または`?demo=true`)にアクセスすると、デモモードが有効になる。それ以外(`/live`のみ、または`demo`パラメータが無い・異なる値)は、既存通り実際のSSE接続を使う通常モードのまま動作する。

**実装方法(判断根拠)**: URLパラメータの読み取りを、`/live/page.tsx`(サーバーコンポーネント)側の`searchParams`で行い、真偽値へ変換した上で`LiveDashboard`(クライアントコンポーネント)へpropsとして渡す設計にした。`LiveDashboard`内で`useSearchParams()`(クライアント側フック)を直接呼ぶ選択肢も検討したが、App Routerでは`useSearchParams()`を使うクライアントコンポーネントを`<Suspense>`境界で包む必要があり、既存のページ構成に、本タスクの範囲を超える変更が必要になる。`searchParams`は、`/live/page.tsx`が(`requireUser()`によりページ自体が既に動的レンダリングされているため)既に受け取れる情報であり、propsとして1回渡すだけで済む、前者の方法を選んだ。

環境変数による切り替えは、依頼書が「URLパラメータ、または、環境変数等」と選択肢を示していたが採用しなかった。判断根拠: 環境変数は、デプロイ環境全体に対して一律に効くため、「通常は本番として使いつつ、動画撮影の時だけ一時的にデモを見せる」という、依頼書の背景(X発信・動画撮影用)が想定する利用シーンには、URLパラメータの方が自然に対応できる(環境変数だと、撮影の度に再デプロイまたは環境変数の切り替えが必要になり、かえって不便)。

## 34. 模擬シナリオの内容

`frontend/src/components/live/demo-scenarios.ts`に、4つの架空シナリオを定義し、ループ再生する。

| シナリオ | 内容 | 特徴 |
|---|---|---|
| `weather` | 今日の天気を聞かれる | 意図分類はヒューリスティックで即座に完了、記憶検索は0件(該当なし扱い)、ツール呼び出し無し。最も軽いパターン。 |
| `dev_progress` | 開発の進捗を聞かれる | 意図分類がLLM経路にフォールボックし、やや時間がかかる。記憶検索は2件ヒット(確信あり)。 |
| `schedule_registration` | 予定を登録してほしいと頼まれる | 意図分類はヒューリスティックで即座、記憶検索1件、`create_app_events`へのツール呼び出しを伴う唯一のシナリオ。 |
| `travel_planning` | 旅行の計画について相談される | 記憶検索がクエリ分解(B7相当)を行い、確信度が「確信度低め」になる、より複雑なパターン。 |

**個人情報を一切含まないことの確認**: いずれのシナリオも、実データからの抽出・加工ではなく、依頼書が例示した「当たり障りのない内容」に沿って、最初から架空のシナリオとして作成した。イベントのペイロード自体(件数・カテゴリラベル・真偽値・所要時間のみ)は、Live-1、4章のプライバシー方針(要約データのみ、発言内容・記憶の中身を含まない)と、構造的に同じ形にしているため、そもそも「発言そのもの」や「記憶の生の内容」を含める余地が無い——模擬データを作る際に個人情報が混入しうる箇所自体が、設計上存在しない。

**「本物のリアルタイム性と演出の境界線」への対応(依頼書2章の制約)**: 各ステップの所要時間(`elapsed_ms`)・遅延(`delayMs`)は、Live-1〜6の報告書に実際に記載された実測値(意図分類のLLM経路2350ms、記憶検索95〜187ms、応答生成410〜932ms、ツール呼び出し15〜88ms等)の桁数・相場感を参考にして設定した——実データの内容ではなく、処理速度の一般的な相場感のみを踏襲することで、「誇張しすぎた演出を避ける」という制約と、「個人情報を一切含まない」という制約を、両立させた(判断根拠)。

## 35. 表示コンポーネントが変更不要だったことの確認結果

**`LiveProcessFlow`・`LiveMetrics`・`LiveEventLog`・`live-event-detail-panel.tsx`のいずれも、本タスクで1行も変更していない。** 変更したのは、以下の3ファイルのみである。

- `use-live-events.ts`: デモモード中に無駄な実SSE接続を張らないための`enabled`オプションを追加(既定値`true`、既存の呼び出し方には一切影響しない)。
- `live-dashboard.tsx`: `useLiveEvents()`/`useMockLiveEvents()`の両方を(Reactのフックのルール上、無条件に)呼び、`demoMode`の値に応じてどちらの結果を使うかを選ぶだけの、数行の変更。加えて、依頼書3章の「控えめな注記」を、この同じファイル内に追加した(表示コンポーネント自体ではなく、既にデータソースを選択する役割を持つ、この橋渡し役のコンポーネントに置くのが自然と判断した)。
- `live/page.tsx`: `searchParams`から`demoMode`を読み取り、`LiveDashboard`へpropsとして渡すだけの変更。

新設したのは、`use-mock-live-events.ts`(再生ロジック)と`demo-scenarios.ts`(シナリオデータ)の2ファイルのみである。これにより、依頼書の必須要件2「`useLiveEvents()`の差し替えのみで実現され、表示コンポーネントは変更されないこと」を、文字通り満たしている——Live-3が予告していた「同じ`{events, status}`の形を返す別のフックを用意し、`LiveDashboard`側で呼び分けるだけで対応できる」という設計が、実装を通じて、そのまま実証された形である。

**判明した、唯一の限界**: デモモード中に、記憶検索・ツール呼び出しの行をクリックすると、`LiveEventDetailPanel`(Live-6)は実際の`/api/live/detail`へリクエストを送るが、模擬データの`invocation_id`/`tool_call_id`に対応する詳細情報は、バックエンドのどこにも存在しないため、常に「詳細情報はまだ準備できていないか、見つかりませんでした」という`not_found`状態が表示される。これは、依頼書の「表示コンポーネントは変更しないこと」という制約を厳格に守った結果として生じる、意図した挙動であり、エラーではない——36章の懸念点として明記する。

## 36. テスト結果

```
npx eslint src/components/live src/app/live   → エラーなし
npx tsc --noEmit(フロントエンド全体)          → エラーなし
npx next build                                → 成功(全43ルート、/liveを含む)
backend/tests/(16件)                          → 全て成功(バックエンドは無変更のため、当然の結果ではあるが確認した)
```

**実装中に発見・修正した、eslintエラー**: `use-mock-live-events.ts`の初期実装は、`useEffect`内で`setStatus("open")`を同期的に呼んでおり、`react-hooks/set-state-in-effect`ルール(カスケード再描画を避けるための、比較的新しいReactのベストプラクティス)に抵触した。デモモードは実際の接続を待つ必要が無い(接続的なライフサイクルが存在しない)ため、`status`の初期値自体を`"open"`にする(`useState<LiveConnectionStatus>("open")`)ことで解消した——`useLiveEvents()`の`"connecting"`始まりとは異なる初期値になるが、これは実際の挙動の違い(実接続を張るか否か)を正直に反映した結果であり、意図的な非対称である。

### 36.1 実際にブラウザを起動しての動作確認(Live-3〜6と同じ手法)

コミットしない一時的な確認用ルート(`live-preview-test-noauth`、`/live/page.tsx`と同じ`demoMode`検出ロジックを、`requireUser()`を経由せずに再現しただけのもの)を使い、Playwright(`chromium`ヘッドレス)で以下を確認した。

- **デモモード(`?demo=1`)**: 「接続状態: 接続中 (デモモード:模擬データを再生中)」と表示され、4つのシナリオが、それぞれ意図分類→記憶検索→応答生成(schedule_registrationシナリオのみツール呼び出しを含む)の順で、自然な間隔で再生されることを、複数時点のスクリーンショットで確認した。メトリクスが、複数シナリオ再生後に正しく集計される(直近3件の平均等)ことも確認した。画面右下に、控えめな「デモ用の模擬データです」という注記が表示されることを確認した。
- **通常モード(`demo`パラメータ無し)**: 実際の`/api/live/stream`への接続を試み(本検証環境にはバックエンドが起動していないため)、`503`で失敗し、「接続状態: エラー」と正直に表示されることを確認した——デモ用の模擬データへ黙ってフォールバックするような実装には、意図的にしていない(通常モードと、デモモードが、完全に独立していることの確認)。
- ブラウザコンソール・ページエラーは、デモモードで0件。通常モードでは、`/api/live/stream`の503エラーがconsoleに1件出力されたが、これはバックエンド不在という検証環境固有の、想定通りの挙動であり、本タスクの変更に起因するものではない。
- 確認用の一時ルートは、検証後に削除し、`git status`で作業ツリーが本タスク本来の変更(`live/page.tsx`の1ファイルの変更+3つの新規ファイル)のみになっていることを確認した。

## 37. 気づいた懸念点・次のステップへの申し送り事項

1. **デモモード中の詳細表示は、常に「見つかりませんでした」になる(35章末尾)。** 表示コンポーネントを変更しない、という制約を優先した結果であり、動画撮影用途では、記憶検索・ツール呼び出しの行を敢えてクリックして詳細を見せる、という使い方は想定していない(処理の流れ・ログ・メトリクスの3点が、デモの主な見せ場になる)。もし将来、詳細パネルも含めて模擬データで見せたい場合は、`LiveEventDetailPanel`(Live-6)自体にモック対応を追加する、独立した拡張が必要になる。
2. **シナリオは現在4つのみ。** 依頼書の「複数、用意する」という要件は満たしているが、長時間の動画撮影で同じ4シナリオがループし続けると、単調に見える可能性がある。`demo-scenarios.ts`の`DEMO_SCENARIOS`配列にシナリオを追加するだけで拡張できる設計にしてあるため、必要に応じて増やすとよい。
3. **シナリオの`invocation_id`は、シナリオ再生のたびに`crypto.randomUUID()`で新規発行しているが、`computeStepStates()`(Live-3)自体は、この値を使ってターンを相関させていない(既知の制約、Live-3・Live-4の申し送り済み)。** そのため、模擬データでも実データでも、この点の挙動は同じであり、デモモード固有の問題ではない。
4. **応答速度への影響**: デモモードは、`demoMode=false`の既存の挙動(実SSE接続のみ)には一切変更を加えていない(`useLiveEvents()`への`enabled`オプション追加は、デフォルト`true`で既存呼び出しの挙動を変えない)。デモモード自体も、バックエンドへの新しいリクエストを一切発行しない(`setTimeout`ベースの、ブラウザ内で完結する再生のみ)ため、バックエンドの応答速度・安定性への影響は、構造的に皆無である。

---

# Sigmaris Live 全体の完了サマリー(Live-1〜Live-7)

依頼書の指示に基づき、Live-1(調査・設計)からLive-7(デモモード)までの、7段階のタスクを通じて、シグマリスの内部処理をリアルタイムに可視化する「Sigmaris Live」機能を、段階的に実装した。以下は、全体を通じての振り返りである。

## 各段階の概要

| 段階 | 内容 | 対象処理 |
|---|---|---|
| **Live-1** | 調査・設計のみ(本番コード変更無し)。既存の処理フローを実コードで整理し、イベント一覧・プライバシー方針(要約データのみ)・fire-and-forgetパターン・SSE配信方式・「本物のリアルタイム性と演出の境界線」の原則を確立した。 | — |
| **Live-2** | 最初の試験導入。`live_events.py`(発行層)・`/api/agent/live/stream`(配信層)・`/live`確認用ページ(テキストログのみ)を実装し、`classify_chat_intent()`1箇所にのみイベント発行を組み込んだ。 | 意図分類 |
| **Live-3** | 本格的なフロントエンド表示への発展。`PROCESS_STEPS`設定配列・処理の流れ(視覚化)・整理されたログ・簡単なメトリクスを実装し、「疎結合な設計」(`useLiveEvents()`のみがSSE接続を知る)を確立した。 | 意図分類のみ(表示のみ拡充) |
| **Live-4** | 他の処理への、イベント発行の拡大。記憶検索・応答生成・ツール呼び出しへ、同じfire-and-forgetパターンを適用。`summarizeResult`/`sourceBreakdownLabel`により、フロントエンドを真に「設定の追加のみ」で拡張できる設計へ改良した。 | 記憶検索・応答生成・ツール呼び出し |
| **Live-5** | 詳細表示、+機密情報のマスキング。ログ行クリックで、マスキング済みの詳細情報(記憶のカテゴリ・要約プレビュー、ツール引数のキー名)を見られるようにした。既存の要約専用SSEチャンネルの認証前提を壊さないよう、新規のJWT必須な詳細取得エンドポイントを追加した(実装着手前に、この設計判断について確認を仰いだ)。 | 記憶検索・ツール呼び出し(応答生成は見送り) |
| **Live-6** | (本報告書には章番号が明示的に振られていないが、Live-5の作業ブランチ内でtool_call_idの追加等、詳細表示関連の実装が行われた——実質的にLive-5と一体の作業として扱われている。) | — |
| **Live-7** | デモモード。X発信・動画撮影用に、個人情報を一切含まない架空のシナリオを、`useLiveEvents()`の差し替えのみで再生できるようにした。 | — |

## 全体を通じて一貫していた設計原則

1. **プライバシー第一**: Live-1が確立した「要約データのみ(件数・真偽値・カテゴリラベル)、発言内容・記憶の中身・応答本文は含めない」という方針は、Live-2〜7の全段階を通じて、一度も緩められなかった。Live-5では、詳細表示という「より踏み込んだ情報を見せたい」という要求と、この方針が緊張関係に立つ場面があったが、その都度、既存の方針を優先する側で判断し、必要な場合は実装前に確認を仰いだ。
2. **fire-and-forgetパターンの一貫した適用**: `classify_chat_intent()`(Live-2)で確立したパターンを、Live-4(記憶検索・応答生成・ツール呼び出し)・Live-5(詳細情報の永続化)まで、新しい設計を持ち込まず、そのまま適用し続けた。
3. **「本物のリアルタイム性」と「演出」の境界線**: Live-1が「記憶検索・意図分類・Evidence検索は、瞬時に完了するバッチ処理であり、段階的な演出は行うべきでない」と結論づけた原則は、Live-4の実装でも、Live-7のデモシナリオの時間設計でも、一貫して守られた。
4. **疎結合設計の実証**: Live-3が確立した「`useLiveEvents()`のみがデータソースを知り、表示コンポーネントはevents配列を受け取るだけ」という設計は、Live-7で実際に「別のフックへ差し替えるだけ」という形で検証され、意図通りに機能した。

## 全体を通じて残っている懸念事項(横断的なまとめ)

1. **`invocation_id`と`message_id`の不一致(Live-2で発生、Live-4・Live-5でも未解消)。** `orchestrator/service.py`側は真の監査ログID、`chat.py`側はローカル生成の`message_id`を使っており、両者は異なるID体系である。現状のフロントエンドはイベント種別のみで状態を判定しており実害はないが、将来、複数ターンの相関が必要になった場合は、`X-Correlation-ID`ヘッダの受け渡し(Live-2で見送った変更)が前提になる。
2. **マスキングの完全性には限界がある(Live-5)。** regexベースの検出であるため、敬称の無い固有名詞や、パターンに一致しない地名表現等は、見逃す可能性がある。詳細パネルには常時、この限界を明示する注記を表示しているが、運用しながらパターンを育てていく必要がある。
3. **`sigmaris_live_event_details`テーブルの保持期間ポリシーが未実装(Live-5)。** マスキング済みとはいえ、個人の記憶・予定に由来する内容を含むため、運用者による保持期間の判断・削除の仕組みの追加が必要。
4. **複数ワーカー構成への非対応(Live-1で明記、以降未解消)。** `LiveEventBus`はプロセス内メモリのみで動作するため、単一uvicornプロセスが前提。将来のスケールアウトでは、Redis pub/sub等への置き換えが必要になる。
5. **応答生成の「文字送り表示」・Evidence検索への拡大は、いずれも未実装のまま(Live-4・Live-5)。** 前者は応答本文の扱いについての追加検討、後者は優先度の観点から、いずれも次のステップとして持ち越されている。
6. **実モデルAPIでの検証は、全段階を通じて実施していない。** 依頼書の制約(サーバーアクセス・APIキーの追加取得を試みない)に従い、いずれの段階も、モック・スクラッチテスト・Playwrightによる模擬イベント注入で検証した。本番環境での実測(処理速度への影響・SSE接続の安定性等)は、運用しながら確認することを推奨する。

## 総括

Sigmaris Liveは、Live-1の調査・設計から、Live-7のデモモードまで、7段階を通じて、「シグマリスの内部処理を、プライバシーに配慮しながら、リアルタイムに可視化する」という当初の目的を、一貫した設計原則のもとで達成した。各段階で、依頼書が明示的に制約した「演出の禁止」「個人情報の非漏洩」「既存機能への悪影響の回避」を、実装のたびに具体的なコード・テストで確認しながら進めてきた。残っている懸念事項(上記6点)は、いずれも「今すぐ対応しないと機能しない」種類のものではなく、将来の拡張・運用時の検討事項として、適切に申し送られている。

---

# 追加調査: 通常モードの接続エラー(`/live`ページ、`?demo=1`無し)

**本タスクは調査・報告のみを目的とし、コードの変更は一切行っていない。**

## 1. `/growth`ページの過去の事例との比較

`docs/sigmaris/`配下を全文検索したが、「`/growth`ページでAGENT_SECRETS関連のエラーが発生し、修正した」という経緯を専用に記録した報告書は見つからなかった。git履歴(`git log --all --grep="AGENT_SECRETS"`)にも、フロントエンド側でこの問題を修正したコミットは見当たらない。**これは、この過去の修正が、コードの変更ではなく、Vercelの環境変数設定画面への追記という、運用上の(バージョン管理の対象外の)操作によって行われたためだと考えられる**——依頼書自身が「フロントエンド側(`.env.local`、または、Vercelの環境変数設定)に設定されておらず」と、コード修正ではなく設定の追加である可能性を示唆していたことと、矛盾しない。

そのため、報告書を参照する代わりに、**実際のコードを直接確認**した。以下、`/growth`ページの認証の仕組みを確認した結果である。

- `/growth`(`frontend/src/app/growth/page.tsx`)は、`fetchAgentJson()`(`frontend/src/lib/backend/agent-client.ts`)経由で、バックエンドの`/api/agent/*`系エンドポイントを呼んでいる。
- `fetchAgentJson()`は、内部で`readAgentHeaders()`(同ファイル)を呼び、`process.env`から、`AGENT_ID`/`AGENT_SECRET`(またはその亜種、`SIGMARIS_AGENT_ID`/`SIGMARIS_AGENT_SECRET`・`SCHEDULE_AGENT_ID`/`SCHEDULE_AGENT_SECRET`・`NEXT_PRIVATE_AGENT_ID`/`NEXT_PRIVATE_AGENT_SECRET`のいずれかの組)、またはJSON形式の`AGENT_SECRETS`を読み取る。
- **この`process.env`は、Next.jsのサーバーサイド実行環境(Vercelにデプロイされた場合はVercelの環境変数設定、ローカル開発時は`frontend/.env.local`)を指す——バックエンド(`backend/.env`)の環境変数とは、完全に独立した、別の設定である。**
- いずれの変数も見つからない場合、`readAgentHeaders()`は`null`を返し、`fetchAgentJson()`は`{data: null, error: "AGENT_SECRETS またはエージェント認証用の環境変数が未設定です。"}`を返す(`agent-client.ts`、69-73行目)。

**結論(1章への回答)**: `/live`ページのSSE接続(`/api/agent/live/stream`)も、**全く同じ`readAgentHeaders()`関数を、そのまま再利用している**(`frontend/src/app/api/live/stream/route.ts`)。`/growth`の過去の事例と、`/live`の現在の症状は、**コードレベルで完全に同一の原因になりうる**——実際に、2章で述べる通り、これがそのまま今回の原因であることを確認した。

## 2. 実際に発生しているエラーの詳細

コードの確認だけでなく、実際にローカルでフロントエンドの開発サーバー(`npm run dev`)を起動し、`/api/live/stream`・`/api/live/detail`へ実際にHTTPリクエストを送り、生のレスポンスを確認した。

```
$ curl -s -i http://localhost:3000/api/live/stream

HTTP/1.1 503 Service Unavailable
content-type: text/plain;charset=UTF-8

AGENT_SECRETS またはエージェント認証用の環境変数が未設定です。
```

```
$ curl -s -i "http://localhost:3000/api/live/detail?eventType=memory_search_finished&key=test"

HTTP/1.1 503 Service Unavailable
content-type: application/json

{"error":"AGENT_SECRETS またはエージェント認証用の環境変数が未設定です。"}
```

この開発環境の`frontend/.env.local`を確認したところ、以下の4項目のみが設定されており、**`AGENT_ID`・`AGENT_SECRET`・`AGENT_SECRETS`のいずれも、含まれていなかった**。

```
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=...
NEXT_PUBLIC_API_URL=...
BACKEND_API_BASE_URL=...
```

**「接続状態: エラー」という表示に至る経路の確認**: `useLiveEvents()`(`frontend/src/components/live/use-live-events.ts`)は、`new EventSource("/api/live/stream")`で接続を試みる。上記の通り、このエンドポイントは、環境変数が無い場合、`Content-Type: text/plain`の503を返す——これは、ブラウザの`EventSource`が期待する`text/event-stream`形式ではないため、ブラウザは接続を即座に失敗と判断し、`source.onerror`が発火する。`onerror`は`setStatus("error")`を呼ぶだけであり(`onmessage`は一度も呼ばれない)、これが「接続状態: エラー、イベントは一切受信できない」という、報告された症状と、完全に一致する。

**バックエンド側(`/api/agent/live/stream`)が期待する認証情報の確認**: `backend/app/routes/agent.py`の`agent_live_stream()`は、`_verify_agent(x_agent_id, x_agent_secret)`のみを要求する(Live-1、4.3節の設計方針通り、要約データのみの配信のためユーザーJWTは不要)。`_verify_agent()`は、`X-Agent-ID`・`X-Agent-Secret`ヘッダの値を、バックエンド自身の環境変数(`backend/.env`の`AGENT_SECRETS`、この開発環境では設定済みであることを確認済み)と照合する。**つまり、バックエンド側の設定は既に正しく、今回の問題は、フロントエンドが、そもそもこのヘッダ自体を送信できていない(送信する前の、Next.js API Route内部で止まっている)ことに起因する**——バックエンドへは、リクエストすら到達していない。

## 3. 特定された原因

**`/growth`ページの過去の事例と、全く同じ原因である。** フロントエンド(Next.jsアプリ、Vercelにデプロイされている本番環境、またはローカル開発時は`.env.local`)側に、エージェント認証用の環境変数(`AGENT_ID`/`AGENT_SECRET`、または`AGENT_SECRETS`)が設定されていない。これらは、バックエンド(`backend/.env`)には設定済みだが、**フロントエンドとバックエンドは、別々にデプロイされた、別々のプロセスであり、環境変数は共有されない**——バックエンド側にどれだけ正しく設定されていても、フロントエンド側に同じ値を改めて設定しない限り、`readAgentHeaders()`は必ず`null`を返し続ける。

Sigmaris Liveのデモモード(`?demo=1`)が正常に動作するのは、Live-7の設計通り、デモモードが`useMockLiveEvents()`(実際のSSE接続を一切行わない、ブラウザ内で完結する模擬データの再生)に切り替わるためであり、この経路は`readAgentHeaders()`・`/api/live/stream`のいずれも経由しない。**通常モードとデモモードの挙動の違いそのものが、問題が「バックエンドの障害」ではなく「フロントエンド側の環境変数設定の欠落」であることの、間接的な裏付けにもなっている**(バックエンド自体に問題があれば、デモモードとは無関係に、他のSSE以外の機能にも影響が及ぶはずだが、そのような報告は無い)。

## 4. 対処に必要な具体的な手順

運用者が行うべき作業は、以下の通り(**依頼書の指示通り、これらの変更は本タスクでは実施していない**)。

### 4.1 設定すべき環境変数

以下のいずれか一方の組み合わせを、**フロントエンド側**に設定する(`readAgentHeaders()`の読み取り優先順位、`agent-client.ts`、19-45行目の通り)。

**選択肢A(推奨): `AGENT_ID`・`AGENT_SECRET`の組を、直接設定する**

| 変数名 | 設定すべき値 |
|---|---|
| `AGENT_ID` | バックエンドの`AGENT_SECRETS`(JSON)に登録済みの、エージェントIDの1つ(例: `sigmaris-orchestrator`) |
| `AGENT_SECRET` | 同エージェントIDに対応する、シークレット値(バックエンドの`AGENT_SECRETS`内、同じキーの値と、完全に一致する必要がある) |

**選択肢B: バックエンドと全く同じ`AGENT_SECRETS`(JSON文字列)を、そのままフロントエンドにも設定する**

| 変数名 | 設定すべき値 |
|---|---|
| `AGENT_SECRETS` | バックエンドの`.env`に設定済みの`AGENT_SECRETS`の値を、そのままコピーする(例: `{"sigmaris-orchestrator":"<バックエンドと同じシークレット>"}`) |

**判断根拠(選択肢Aを推奨する理由)**: `readAgentHeaders()`は、`AGENT_ID`/`AGENT_SECRET`が設定されていれば、それを`AGENT_SECRETS`より優先して使う(19-32行目)。選択肢Bは、JSON文字列全体をコピーする必要があり、値の一部が欠けた場合の`JSON.parse()`失敗(43-47行目、`catch`で`null`を返す)のリスクがある一方、選択肢Aは、2つの単純な文字列を設定するだけで済み、設定ミスのリスクが低い。**いずれの選択肢でも、値自体は、バックエンドの`AGENT_SECRETS`に既に登録されている、正しいエージェントID・シークレットと、完全に一致している必要がある**(新しい値を作るのではなく、既存の値を、フロントエンド側にも複製する)。

### 4.2 設定すべき場所

- **本番環境(Vercelにデプロイされている場合)**: Vercelのプロジェクト設定 → Environment Variables画面で、上記の変数を追加する。**`NEXT_PUBLIC_`という接頭辞は付けないこと**(`NEXT_PUBLIC_`が付いた変数は、ブラウザ側のJavaScriptバンドルに埋め込まれ、誰でも閲覧できる状態になってしまう——`readAgentHeaders()`は、Next.jsのサーバーサイド専用コード内でのみ実行されるため、`NEXT_PUBLIC_`無しの、サーバー限定の環境変数として設定する必要がある)。設定後、Vercel上で再デプロイ(環境変数の変更は、次回のデプロイから反映される)。
- **ローカル開発環境**: `frontend/.env.local`に、同じ変数を追記する。追記後、開発サーバー(`npm run dev`)の再起動が必要(Next.jsは起動時に環境変数を読み込むため)。

### 4.3 設定後の確認方法

設定・再デプロイ(または開発サーバー再起動)後、以下を確認するとよい。

1. `curl -i https://<本番ドメイン>/api/live/stream`(または、ローカルなら`http://localhost:3000/api/live/stream`)を実行し、503ではなく、`Content-Type: text/event-stream`のレスポンスが返ってくることを確認する。
2. `/live`ページ(通常モード、`?demo=1`無し)を開き、「接続状態: 接続中」と表示されることを確認する。
3. 実際に`/chat`で会話し、意図分類・記憶検索・応答生成等のイベントが、`/live`ページに反映されることを確認する。

## 気づいた懸念点

1. **フロントエンド・バックエンドで、同じシークレット値を、2箇所に複製して管理する必要がある、という構造自体は、今回の問題の根本的な原因である。** 将来、シークレットをローテーションする際は、バックエンド・フロントエンドの両方を、同時に更新する必要があり、今回と同種の設定漏れが再発するリスクが構造的に残る。次のステップとして、シークレット管理を一元化する(例: 両方が同じシークレットマネージャーを参照する)ことも、検討の価値があると考えられるが、これは本調査の範囲を超える、より大きな設計判断であるため、提案に留める。
2. **`/growth`・`/timeline`・`/memory`等、同じ`fetchAgentJson()`/`readAgentHeaders()`を使う、他のページも、フロントエンド側の環境変数が正しく設定されていなければ、同様のエラーになりうる。** 今回`/live`だけが報告されたのは、たまたま`/live`ページが最近追加された機能で、運用者が実際に開いて試したタイミングが今回だった、という可能性がある——`/growth`が過去に同じエラーで修正された経緯があることから、その時点で環境変数は設定されたはずだが、`/live`固有の追加設定が必要なわけではなく(`/growth`と全く同じ変数を共有する)、**`/growth`の修正時に設定された環境変数が、その後何らかの理由で失われた(例えば、Vercelプロジェクトの再作成、環境変数の誤削除等)可能性**も、否定はできない。運用者に、現在Vercelに設定されている環境変数の一覧を、直接確認してもらうことを推奨する。
3. **本調査は、ローカル開発環境での再現・コード確認に基づくものであり、実際の本番Vercel環境の環境変数設定を、直接確認したわけではない**(依頼書の制約上、追加のサーバー・環境アクセスは行っていない)。ローカル環境で観測した503エラー・エラーメッセージは、コード上`/growth`・`/live`のいずれでも、環境変数が無い場合に必ず発生する、条件分岐の結果であるため、本番環境でも同じ条件(環境変数未設定)であれば、同じ症状になることは、コードから確実に言えるが、本番環境で実際に環境変数が設定されているか否かの最終確認は、運用者にしかできない。

---

## 追加調査(2回目): 環境変数を揃えた後も、接続エラーが解消しない件

**運用者が、フロントエンド側の`AGENT_SECRETS`を、バックエンドと同じ値に揃えて再デプロイした後も、`/live`ページの通常モードで、依然として「接続エラー」になる**、という報告を受け、再調査した。**本調査も、コードの変更は一切行っていない。**

### 調査結果: 本番バックエンド自体に、Sigmaris Liveのルートが存在しない

`docs/sigmaris/phase_e_report.md`(31行目)が、過去に「`curl https://api.sigmaris.jp/`という、未認証・読み取り専用の疎通確認は、本番の設定・データに一切影響を与えない」という前例を記録していたため、同じ方法で、本番のバックエンド(`https://api.sigmaris.jp`、`docs/cloudflare-tunnel.md`で確認済みの、実際の本番ドメイン)へ、直接、読み取り専用のリクエストを送り、実際の挙動を確認した。

```
$ curl -i https://api.sigmaris.jp/api/agent/live/stream
HTTP/1.1 404 Not Found
{"detail":"Not Found"}

$ curl -i https://api.sigmaris.jp/api/agent/live/detail
HTTP/1.1 404 Not Found
{"detail":"Not Found"}

$ curl -i https://api.sigmaris.jp/api/agent/self/model   (比較用、既存の、以前から本番稼働している別エンドポイント)
HTTP/1.1 401 Unauthorized
{"detail":{"error":"X-Agent-ID and X-Agent-Secret headers are required."}}
```

**この違いが、決定的な手がかりになった。** `/api/agent/self/model`(Sigmaris Liveより前から存在する、既存のエンドポイント)は、認証ヘッダが無い場合、`_verify_agent()`が正しく反応し、`401`(「ヘッダが必要です」)を返す——つまり、**このルート自体は、本番のFastAPIプロセスに存在し、正しく動いている。** 一方、`/api/agent/live/stream`・`/api/agent/live/detail`は、認証ヘッダの有無に関わらず(ヘッダを付けたリクエストでも同じ結果だった)、**常に`404`**——これは、認証で弾かれているのではなく、**そもそも、そのURLパスに対応するルート自体が、本番のFastAPIアプリケーションに登録されていない**ことを意味する(FastAPIは、ルートが存在しないパスへのリクエストに対しては、認証処理が実行される前に、ルーティングの時点で404を返す)。

念のため、本番のOpenAPIスキーマ(`https://api.sigmaris.jp/openapi.json`、これも読み取り専用で、FastAPIが標準で公開する、自身のAPI定義)を取得し、実際に本番へ登録されている、全57個のパスを確認した。**`/api/agent/live/stream`・`/api/agent/live/detail`は、この一覧のいずれにも含まれていなかった。** 一方、`/api/agent/growth/*`(`/growth`ページが使う、4つのエンドポイント)・`/api/app/chat/threads`等(Sigmaris Liveより前のフェーズで実装された機能)は、いずれも一覧に含まれていることを確認した。

### 結論: フロントエンドの環境変数ではなく、本番バックエンドの未再デプロイが、真の原因

以下の一連の事実から、**本番サーバー(Ubuntu Server上のFastAPIプロセス)が、Sigmaris Live(Live-1〜7)を実装したコードで、まだ再起動・再デプロイされていない**、と結論づける。

1. `/api/agent/live/*`は、404(ルート未登録)であり、401(認証エラー)ではない。
2. 同じ`_verify_agent()`ガードを持つ、より古いエンドポイント(`/api/agent/self/model`)は、正しく401を返す——バックエンド自体は正常に稼働しており、Cloudflare Tunnel・ルーティングにも問題は無い。
3. 本番のOpenAPIスキーマに、`/api/agent/live/*`のいずれも登録されていない。
4. `/growth`が使う`/api/agent/growth/*`(Sigmaris Liveより前に実装された機能)は、本番に登録済みである——つまり、本番のコードは、Sigmaris Live着手**前**のある時点で止まっている。

**1回目の調査(環境変数の欠落)は、実際に存在した、正しい問題だった**——運用者がこれを修正したことで、フロントエンドの`/api/live/stream`・`/api/live/detail`(Next.js API Route)自身は、正しくエージェント認証ヘッダを送信できるようになったはずである。しかし、その送信先である**本番バックエンドに、受け取る側のルートがまだ存在しない**ため、リクエストは`404`で返ってきてしまう。フロントエンドの中継ルート(`frontend/src/app/api/live/stream/route.ts`)は、`upstream.ok`が`false`の場合、`Sigmaris Live配信への接続に失敗しました (404): ...`という、独自のエラーメッセージを、404のまま返す設計になっている(31行目付近)——ブラウザの`EventSource`は、`text/event-stream`以外のレスポンスを、通常のHTTPステータスに関わらず接続失敗と見なすため、症状としては、1回目の調査時と同じ「接続状態: エラー」に見えるが、**実際に発生しているエラーの中身(503→404)は変わっている**、という点が、今回の調査で新たに判明した事実である。

### 運用者に確認・対応してほしいこと(引き続き、コードの変更は本調査に含まれていない)

1. **ブラウザの開発者ツール(Network タブ)で、`/api/live/stream`へのリクエストが、実際に`404`になっていることを確認する**(1回目の調査時点の`503`から、変化しているはずである)。これにより、今回の切り分けが、実際の本番環境でも正しいことを、直接確認できる。
2. **本番のUbuntu Server上で、リポジトリを最新化し(`git pull`)、バックエンドのsystemdサービス(`sigmaris-backend`、または実際のサービス名)を再起動する。** これにより、`routes/agent.py`の`/live/stream`・`/live/detail`エンドポイントが、本番のFastAPIプロセスに反映される。
3. 再起動後、`curl -i https://api.sigmaris.jp/api/agent/live/stream`(認証ヘッダ無し)を実行し、`404`ではなく`401`(「X-Agent-ID and X-Agent-Secret headers are required.」)が返ってくることを確認する——これが、ルート自体が本番に反映されたことの、直接的な確認になる。
4. その上で、`/live`ページ(通常モード)を開き、「接続状態: 接続中」になることを確認する。

### 気づいた懸念点(2回目の調査分)

1. **本番バックエンドの更新は、`git pull`+サービス再起動という、手動の運用作業に依存しており、コードのマージ(mainへのpush)と、本番反映は、別のタイミングで発生する。** 今回のように、フロントエンド側だけを追いかけて調査すると、見落としやすい——次回以降、同種の「コードは直したはずなのに直らない」という報告を受けた際は、**まずバックエンドが実際にどのコミット時点で動いているかを、直接確認する**(今回行ったような、既知のルートの有無を確認する、疎通確認)ことを、優先的な調査手順として推奨する。
2. **本番のFastAPIプロセスが、正確にどのコミット時点のコードで動いているかを特定する、バージョン情報(gitコミットハッシュ等)を返すエンドポイントが、現状存在しない**(`/health`・`/api/health`は、`{"status":"ok", ...}`のみを返す)。今回は、既知のルートの有無という、間接的な方法で「Sigmaris Live着手前」までは絞り込めたが、正確な時点までは特定できなかった。将来、同種の調査を素早く行えるようにするため、`/health`にビルド時のgitコミットハッシュを含める、といった改善を、次のステップとして提案する(本調査の範囲を超えるため、実装はしていない)。

---

## Sigmaris Live のサイドバー化（デザイン統一 第五段階、2026-07-21）

デザイン統一の最終段階（`docs/sigmaris/frontend_design_unification_report.md` 第五段階）で、当初からの要望である「Sigmaris Live を `/chat` の右サイドバーとして開閉表示し、メッセージ送信直後に内部処理をその場で見られるようにする」を実装した。**Live-1 で確立した「演出の禁止」原則・既存のイベント設計・SSE 配信は一切変更していない**（新規イベント・疑似プログレスは追加していない）。

### 実装の要点（既存資産の再利用）

- **`/live` 独立ページは削除せず不変更**。デモモード（`?demo=1`）のフルスクリーン表示（X発信・動画撮影用）という独自用途を保持する。
- 新規は **`frontend/src/components/live/live-sidebar-panel.tsx`（表示専用の薄い composition）** と、`ChatWorkspace` への配線のみ。**葉コンポーネント（`LiveProcessFlow`/`LiveMetrics`/`LiveEventLog`）・`useLiveEvents`・`process-steps`/`metrics`/`types`/`live-event-detail-panel` は `/live`(LiveDashboard) とサイドバーで共有**し、重複実装はゼロ。「1つのデータソース(events)を複数の表示コンポーネントへ配る」という Live-3 の設計をそのまま踏襲した。
- **リアルタイム性**: `ChatWorkspace` で `useLiveEvents(undefined, { enabled: liveOpen })` を1回だけ呼び、`events`/`status` をパネルへ渡す。パネルを開いて `/chat` にメッセージを送ると、そのターンの意図分類・記憶検索・応答生成・ツール実行のイベントが `LiveProcessFlow`/`LiveMetrics`/`LiveEventLog` にリアルタイム反映される。
- **SSE の開閉制御**: 既存 `useLiveEvents` の `enabled` オプションを使い、**閉時は `EventSource` を一切生成しない**（`enabled=liveOpen`）。フック呼び出しは1回のみのため、デスクトップ列・モバイルドロワーの両描画があっても SSE 接続は常に最大1本。
- **`/chat` の常時ダーク保護との整合**: パネルは `ChatWorkspace` の `.dark` サブツリー内・`bg-[#171717]` 基調で描画され、第二段階の常時ダーク保護に自然に乗る（light テーマでもダーク）。`/chat` の視覚デザイン・保護コードは不変更。

### 本番反映後に確認してほしいこと

- 上記「運用者に確認・対応してほしいこと」の通り、Sigmaris Live のイベントが実際に流れるには、**本番バックエンドに `routes/agent.py` の `/live/stream`・`/live/detail` が反映されている必要がある**（未反映だと `/api/live/stream` が 404 になり、サイドバーも「接続状態: エラー」になる）。サイドバーのリアルタイム表示を確認する前に、まず本番バックエンドの反映状況（既知ルートの疎通）を確認すること。
- `/chat` ヘッダー右の Live トグルで開閉できること、開いた状態でメッセージ送信→処理がリアルタイム表示されること、閉時に SSE 接続が張られないこと（Network タブで確認）、light テーマでも `/chat`・パネルがダークのままであること。
