# グローバル状態方式 移行前調査レポート

**目的:** 「スレッド＝UI上の入れ物」「記憶＝全スレッド共通のグローバル状態(`sigmaris_global_state`)に一元化」という設計変更に向けて、現行コードベースの依存箇所と影響範囲を洗い出す。
**性質:** 調査レポートのみ。本ドキュメント作成時点でコードは一切変更していない。
**調査日:** 2026-07-02
**調査範囲:** `backend/app/` 全体、`supabase/migrations/` 全24ファイル、`backend/app/services/proactive/scheduler.py`、`backend/app/services/orchestrator/`、`frontend/src`（スレッドID/セッションID関連）、`docs/sigmaris/`。

---

## 0. アーキテクチャの前提（誤解しやすい点）

このリポジトリには「チャットエンジン」が実質**2つ**ある。

1. **`backend/app/services/chat.py`**（887行）— OpenAI Responses API を直接叩く、ツール実行（カレンダー・マップ等）付きの「schedule-agent」本体。`POST /api/chat/stream`（フロントエンド直呼び用）と `POST /api/agent/chat/complete` / `/api/agent/chat/stream`（オーケストレーター経由）の両方から呼ばれる。
2. **`backend/app/services/orchestrator/service.py`**（643行）— 上記1を「schedule-agent」としてHTTP経由で呼び出し、Persona（人格）を適用し直す統括層。`POST /api/orchestrator/chat` / `/chat/stream` から呼ばれる。

さらにフロントエンド（Next.js）は **`frontend/src/lib/chat-threads.ts`** から `chat_threads` / `chat_messages` テーブルへ**直接**Supabaseクライアントで読み書きしており、バックエンドの `app_chat_data.py` とは**独立した書き込み経路**になっている（同じテーブルに対する2つの独立したCRUD実装）。この二重性は5章で詳述する。

---

## 1. 現状のプロンプト組み立てフロー図

### 1-A. `/api/orchestrator/chat`（Webフロントエンド・WearOSが使う経路）

```
frontend (browser)
  → POST /api/orchestrator/chat  (Next.js API route, frontend/src/app/api/orchestrator/chat/route.ts)
      - Supabaseセッションからuser取得、認可ヘッダー構築 (readBackendAuthHeaders)
      - { messages, thread_id, context } を組み立てて転送
  → POST http://backend/api/orchestrator/chat  (backend/app/routes/orchestrator.py)
      - _require_jwt() で Authorization ヘッダーのみ検証（形式チェックのみ、実検証は後段）
  → orchestrator/service.py :: run_orchestrator_chat()
      1. persona = load_persona()                         # persona.md 読み込み(ハッシュ付き)
      2. asyncio.gather(
           get_current_user(jwt),                          # Supabase Auth検証(ここで実JWT検証)
           _cached_user_profile(jwt),                       # user_fact_profile (5分TTLキャッシュ)
           _cached_self_model(jwt),                         # sigmaris_self_model (5分TTLキャッシュ)
           _cached_active_trends(jwt),                      # user_trend_items (5分TTLキャッシュ)
         )
      3. fact_items = _cached_fact_items(jwt, user_id)      # user_fact_items（RLS優先→service_roleフォールバック）
      4. start_invocation()                                 # agent_invocation_audit_logs へ開始記録
      5. profile_context の組み立て:
           build_profile_context(fact_profile)               # 200文字に切り詰め
           + build_facts_context(fact_items, top_n=5)         # importance×confidence上位5件
           + _build_trends_context(active_trends, top 3)
           ↓ さらに _build_memory_context() で上書き:
             if LOCAL_LLM_ENABLED:
                search_relevant_memories(latest_user_text, ...)  # pgvector RAG検索(top5)
             else:
                上のprofile_context+facts_ctx+trends_ctxをそのまま使用
      6. self_model_context = _build_self_model_context(self_model)  # identity 150文字 + goals上位3
      7. call_schedule_agent(messages, thread_id, user_profile_context, self_model_context, ...)
           → HTTP POST http://127.0.0.1:8000/api/agent/chat/complete
             body: { thread_id, messages, persist_thread: False,
                      system_override: user_profile_context + self_model_context + 固定英文注記,
                      context: {...} }
      8. [受信側] routes/agent.py :: agent_chat_complete()
           → chat.py :: run_chat_completion(system=payload.system_override, persist_messages=False)
               a. profile_context2 = get_profile_context(jwt)      # ← app_profile_data.py、上とは別の呼び出し
               b. attachment_facts = build_attachment_facts(...)
               c. route = classify_chat_intent(client, model, messages, attachment_facts)  # 意図分類(LLM呼び出し1回)
               d. router_instruction = build_specialized_router_instruction(route)
               e. system_prompt = build_system_prompt(
                    system_override,        # ← orchestratorが作ったuser_profile+self_model文脈
                    ai_tone_instruction,     # profile.aiTone依存
                    attachment_facts,
                    router_instruction,     # ← 意図分類結果(ターンごとに変わりうる)
                    agent_mode=True,        # persist_messages=Falseなので固定
                  )
               f. client.responses.create(model=OPENAI_MODEL, instructions=system_prompt,
                    input=[全messages...], tools=[...], previous_response_id=None)
                    # ※ previous_response_id は毎回 None。ターンをまたいだ会話継続は
                    #   OpenAI側の会話状態ではなく「毎回全messagesを送り直す」方式。
               g. ツール呼び出しがあれば実行 → 結果を積んでループ(最大8回、同一リクエスト内)
               h. persist_messages=False のため chat_messages への保存はスキップ
      9. [orchestrator側] rewrite_with_persona(schedule_result.text, persona)  # 人格リライト(LLM呼び出し1回)
      10. replace_forbidden_assistant_names(rewrite.text)
      11. finish_invocation()                                # audit_logs更新
      12. active_inquiry.get_inquiry_question()               # 欠落fact質問の追加(最大1件、2秒タイムアウト)
      13. asyncio.create_task: memory_extractor.extract_from_conversation()   # fire-and-forget
      14. asyncio.create_task: _cognitive_layer_bg()          # decision_log + internal_state更新(fire-and-forget)
  → レスポンス { ok, text, thread_id, invocation_id, agent_id, used_fallback }
```

**1リクエストあたりのLLM呼び出し回数（概算）**: 意図分類1回 + 本応答1〜8回（ツール呼び出し次第） + Persona書き換え1回 + （fire-and-forgetで）記憶抽出1回 = 最低3回、ツール多用時は10回近くになりうる。

### 1-B. `/api/chat/stream`（フロントエンドがオーケストレーターを経由せず直接叩く経路）

`routes/chat.py` → `chat.py::stream_chat_completion_ui(persist_messages=True)` を直接呼ぶ。1-A のステップ8以降とほぼ同じだが、**ユーザーの長期記憶（fact/self_model/trend）はここには一切注入されない**（`system=None` で呼ばれるため、`build_system_prompt`の`base_system`は空）。この経路を使うと事実上「記憶なしのカレンダーエージェント」になる。

---

## 2. スレッド依存箇所の一覧

| ファイル | 関数 | thread_id の用途 |
|---|---|---|
| `backend/app/services/app_chat_data.py` | `get_chat_thread()` | `chat_threads`テーブルをidで1件取得（存在確認のみ） |
| `backend/app/services/app_chat_data.py` | `replace_chat_messages()` | **`thread_id`＋`user_id`で`chat_messages`を全削除→渡された`messages`配列を全件再INSERT**（差分更新ではなく毎回全置換） |
| `backend/app/services/chat.py` | `run_chat_completion()` / `stream_chat_completion_ui()` | `persist_messages=True`時、冒頭で`get_chat_thread(jwt, thread_id)`が存在しなければ例外。応答後に`replace_chat_messages()`を呼ぶ |
| `backend/app/services/orchestrator/service.py` | `run_orchestrator_chat()` | 受け取った`thread_id`をそのまま`call_schedule_agent()`に転送。実際の会話履歴は**呼び出し元が送ってきた`messages`配列**（DBから取得し直してはいない） |
| `backend/app/services/orchestrator/schedule_agent_client.py` | `_build_payload()` | `"persist_thread": False`固定。schedule-agent側では保存されない |
| `backend/app/routes/agent.py` | `agent_chat_complete()` / `agent_chat_stream()` | `payload.thread_id or uuid4()`。`persist = payload.persist_thread and payload.thread_id is not None` |
| `backend/app/routes/chat.py` | `chat_stream()` | `ChatStreamRequest.threadId`必須（min_length=1）。`persist_messages`はデフォルトTrueのため保存経路が有効 |
| `backend/app/services/proactive/actions.py` | `_run_action()` | プロアクティブ実行ごとに`f"proactive-{action_name}-{uuid4()}"`という**使い捨てのthread_id**を生成。過去のプロアクティブ会話とは接続されない |
| `frontend/src/lib/chat-threads.ts` | `listChatThreads/createChatThread/getChatThread/renameChatThread/deleteChatThread/listChatMessages/replaceChatMessages` | Next.jsサーバーサイドから**Supabaseに直接**`chat_threads`/`chat_messages`をCRUD。バックエンドとは独立した書き込み経路 |
| `frontend/src/app/api/chat/threads/route.ts`, `frontend/src/app/api/chat/threads/[threadId]/route.ts` | REST風API | スレッド一覧・個別スレッドのHTTPエンドポイント |
| `frontend/src/app/api/orchestrator/chat/route.ts` | `POST` | ブラウザから受け取った`threadId`をそのままバックエンドへ転送するのみ（フロント側での永続化はしない） |

### スレッドをまたいだ際の文脈引き継ぎの実態

- **Fact Memory（`user_fact_items`）・Self Model・Trend**: スレッドに紐付いていない（`user_id`のみに紐付く）。**どのスレッドからでも同じ内容が注入される**ため、この部分は既に「グローバル状態」相当の設計になっている。
- **会話の生ログ（`chat_messages`）**: 完全にスレッド単位。別スレッドを開くと過去の会話文脈は一切引き継がれない（要約もされない）。
- **Mem0等の要約ライブラリ**: リポジトリ全体を検索したが**一切導入されていない**（`grep -rni mem0`で0件）。「変更前の想定」に書かれている「Mem0で要約・検索」は現状コードには存在せず、ドキュメント上の設計意図のみ。
- **`sigmaris_decision_log`/`sigmaris_internal_state`**: これらもユーザー単位のグローバル状態（thread_id列を持たない）。ただし内容は「chat_turn:xxxx」という空疎な記録のみ（前回調査済み・別レポート参照）。

### 複数スレッド同時オープン時の競合リスク

`replace_chat_messages()`は「渡された`messages`配列全体で対象スレッドを完全上書き」する設計のため、**同一スレッドに対して2つのタブ/デバイスから同時にメッセージを送信すると、後から完了したリクエストが先に完了したリクエストのメッセージを消し飛ばすリスクがある**（read-modify-write方式で、DBレベルの楽観ロック・バージョンチェックが一切ない）。異なるスレッド同士なら`thread_id`が違うため競合しない。

---

## 3. 既存記憶関連実装の完成度

| 実装 | 完成度 | 根拠 |
|---|---|---|
| `user_fact_items`（事実記憶） | ✓ | スキーマ完備（category/key/value/confidence/importance_score/privacy_level/is_deleted/is_stale/embedding vector(768)）。`memory_extractor.py`が毎チャットターン後にfire-and-forgetで抽出・upsert。`build_facts_context()`で応答生成に注入。`memory_validator.py`が毎日6:30に減衰・矛盾検出・論理削除を自動実行 |
| `user_fact_profile`（スカラー型プロフィール） | ✓ | `user_fact_items`と並行運用。`get_null_fields()`で欠落項目を検出し`active_inquiry.py`が自然に質問生成 |
| pgvector + nomic-embed-text RAG | △ | 実装は完成（`memory_search.py`、768次元、Ollama `/api/embeddings`呼び出し、`search_fact_memory` RPC）。**ただし`LOCAL_LLM_ENABLED=false`の場合は`generate_embedding()`が即座に空リストを返し、検索処理全体がスキップされる**（`orchestrator/service.py::_build_memory_context()`のif分岐）。ユーザーが言う「285件・ベクトル化済み」は`LOCAL_LLM_ENABLED=true`での運用を前提としている可能性が高い |
| Mem0等の要約ライブラリ | ✗ | 未導入。関連コード・依存関係ともに存在しない |
| 「決定事項」「方針」の特別扱い保存 | △ | `sigmaris_decision_log`テーブルは存在し、`decision_type`に`proposal`（提案）は含まれるが、実際の書き込みは`orchestrator/service.py::_cognitive_layer_bg()`から`title=f"chat_turn:{invocation_id[:8]}"`という**汎用ログのみ**。「この会話でユーザーがこう決めた」という意味のある方針記録は自動化されていない。`experience_layer.py::record_experience()`（category='proposal'含む）は書き込み経路が`POST /api/agent/experience/record`のみで、通常の会話フローからは呼ばれない（別レポートで詳細確認済み） |
| スレッド横断の文脈保持 | ✗ | `chat_messages`はスレッドで完全に分離。Fact Memory/Self Model/Trendはグローバルだが「直近の会話の流れ」はスレッドをまたぐと失われる |

---

## 4. 非同期処理基盤

- **ジョブキュー等の専用ミドルウェアは存在しない**。全ての非同期・定期処理は`backend/app/services/proactive/scheduler.py`の**単一プロセス内`APScheduler`（`AsyncIOScheduler`）**で実装されている。`main.py`の`lifespan`で`startup_scheduler()`/`shutdown_scheduler()`を呼び出し、FastAPIプロセスと寿命が一致する（別プロセス・別サーバーではない）。
- 現在14ジョブ登録済み（`heartbeat`毎分から週次ジョブまで）。Pushover通知（`proactive/notifier.py`）・リサーチエージェント（毎日7:00、`research_agent.py`）はいずれもこのAPSchedulerジョブとして実装。
- systemdタイマー・cron（OS側）・Celery/RQ等の外部ジョブキューは使われていない。
- **「応答後に裏側で記憶を更新する」パターンは既に実装済みで、乗せられる**: `orchestrator/service.py`が`asyncio.create_task(...)`でfire-and-forgetタスクを2つ起動している（`memory_extractor.extract_from_conversation()`と`_cognitive_layer_bg()`）。`sigmaris_global_state`更新もこのパターン（応答を返した直後に`asyncio.create_task`でグローバル状態を非同期更新）にそのまま乗せられる。**新規の非同期基盤は不要**。ただし現状のfire-and-forgetタスクは例外を握りつぶすのみで（`try/except + logger.exception`）、失敗時のリトライや失敗検知の仕組みはない点は留意。

---

## 5. DBスキーマ全体像

24マイグレーションを時系列で整理（詳細は前回の別レポートと重複するため要点のみ）。

**アプリ基盤系**: `profiles` `saved_locations` `calendar_connections` `import_jobs` `events` `event_travel_plans` `chat_threads` `chat_messages` `push_subscriptions` `travel_notification_deliveries` `billing_customers` `subscriptions` `event_audit_logs` `agent_invocation_audit_logs`

**記憶系（ユーザー単位・スレッド非依存 = 実質グローバル）**: `user_fact_profile` `user_fact_items`(embedding vector(768)列あり) `user_fact_history` `user_trend_items` `sigmaris_self_model` `sigmaris_self_discrepancies` `sigmaris_narrative` `research_items` `x_post_history`

**認知アーキテクチャ系（ユーザー単位・スレッド非依存）**: `sigmaris_constitution` `sigmaris_experience` `sigmaris_curiosity_queue` `sigmaris_internal_state` `sigmaris_decision_log`

**`sigmaris_global_state`との衝突・重複の検討**:

- **列レベルでの直接衝突はない**（同名テーブル・同名列は存在しない）。
- ただし**役割レベルでの重複**が複数箇所で発生する:
  - `decisions_log`（想定）↔ 既存の`sigmaris_decision_log`テーブル。**新設せず既存テーブルを本格稼働させる方が自然**（既に`decision_type`/`reason`/`constitution_refs`/`memory_refs`/`experience_refs`/`outcome`という十分なスキーマがあり、中身が空疎なだけ）。ここに新しく`sigmaris_global_state.decisions_log`(JSONB)を作ると、同じ情報を持つテーブルが2つ並立し、どちらが正になるか曖昧になる。
  - `active_topics`（想定）↔ `user_trend_items`（behavior/mood等のカテゴリで近い役割）や`sigmaris_curiosity_queue`。完全一致ではないが機能的に近い。
  - `recent_raw_turns`（想定）↔ `chat_messages`（スレッド単位の生ログ）。グローバル状態側に「直近の生ターン」を持たせる場合、`chat_messages`との間でどちらが正の会話ログかを明確にする必要がある（二重管理は事故の元）。
- **シングルトン/ユーザー単位1行という設計パターンは既に前例がある**: `sigmaris_self_model`（`create unique index ... ((true))`でシングルトン制約）、`sigmaris_internal_state`（同様のシングルトンパターン、ただし現状ユーザー単位ではなく**サービス全体で1行**）。`sigmaris_global_state`を「ユーザーごとに1行」にする場合、`sigmaris_internal_state`が「サービス全体で1行」である点との整合性を先に決める必要がある（マルチユーザー化を見据えるなら`sigmaris_internal_state`も`user_id`列を追加すべきだが、現状は単一ユーザー運用前提で単一行になっている）。

---

## 6. ローカルLLM(Ollama)切り替え時の影響

- 分岐点は`local_llm.py::LLMRouter`のみ。`TaskType`（ROUTING/MEMORY_EXTRACTION/SELF_REFLECT/SUMMARIZE）は`LOCAL_LLM_ENABLED=true`かつOllama疎通確認済みなら`LocalLLMClient`（Ollama `/api/chat`）へ、`COMPLEX_REASONING`は常にOpenAIへ固定ルーティングされる。
- **チャット本体（`chat.py`の`client.responses.create()`）はこのルーターを一切経由しない**。OpenAI Responses APIを直接使っており、`LOCAL_LLM_ENABLED`はチャット応答生成そのものには影響しない。影響が出るのは「記憶抽出」「意図ルーティング判断の一部」「自己反省」「要約」「埋め込み生成」（`memory_search.py::generate_embedding()`）に限られる。
- **Ollama側にOpenAIのプロンプトキャッシュに相当する仕組みは、このコードでは活用されていない**。`LocalLLMClient.chat()`は`stream=False`の単発`/api/chat`呼び出しのみで、`keep_alive`やプロンプトのプレフィックス再利用を意識した実装にはなっていない（Ollamaはモデルロード状態の保持は行うが、KVキャッシュの明示的な再利用はコード側で設定していない）。
- ローカルLLM切り替え時の性能差は、モデルサイズ（`qwen2.5:14b`想定）とハードウェア次第で変動が大きく、本調査だけでは定量評価できない。ベンチマークが必要。

---

## 7. プロンプト構造とOpenAIキャッシュ適合性（重要な懸念）

- `chat_prompts.py::build_system_prompt()`の結合順序: `[base_system, ai_tone_instruction, router_instruction, rules(固定90行相当), attachment_facts]`。
- **`router_instruction`（意図分類の結果、ターンごとに変わりうる）が、大きな固定ルール文（`rules`）より前に配置されている。** さらに`rules`内3番目の要素に`f"現在日時は... {now_jst}"`という**分単位で変化するタイムスタンプ**が埋め込まれている。
- OpenAIのプロンプトキャッシュはプレフィックス一致方式のため、**この構造では固定の長い指示文（rules）の手前に毎回変化する要素が来ており、キャッシュヒットが発生しにくい配置になっている**。理想的には「不変・長大な指示文を先頭に、可変・短い要素（現在時刻・意図分類結果・ユーザー固有コンテキスト）を末尾に」configureする方がキャッシュ効率が良い。
- `rules`配列自体はおよそ数千文字（英日混在、概算で1,500〜2,500トークン程度）の固定指示。ここに`orchestrator/service.py`側で組み立てる`system_override`（プロフィール要約200文字＋fact上位5件＋self_model 150文字など、合計でも1,000トークン未満）が加わる。**システムプロンプト全体は概算で2,000〜4,000トークン程度**とみられ、絶対量として大きすぎるわけではない。
- 現在使用中のモデルは`config.py`のデフォルト`gpt-5.4-mini`（`backend/.env`に`OPENAI_MODEL`の上書き設定なし、デフォルトのまま稼働）。このモデル世代の正確なコンテキストウィンドウ上限・キャッシュTTL・最小キャッシュブロックサイズについては、本調査ではOpenAI公式ドキュメントの直接確認ができておらず、**数値を断定できない**。グローバル状態移行の設計時に公式ドキュメントで最新仕様を確認することを推奨する。
- **`previous_response_id`が毎ターンNoneにリセットされている**（1-Aで詳述）ため、OpenAI側の会話状態保持機能自体を使っておらず、ターンが進むごとに`input`配列（全会話履歴）が線形に増大していく。スレッドが長くなるほど1リクエストあたりの送信トークン数が増え、キャッシュの効きにくさと相まってコスト・レイテンシに直結する。**グローバル状態方式では「直近生ターンのみ送り、それより前はグローバル状態の要約で代替する」設計にすることで、この問題を根本的に軽減できる可能性がある。**

---

## 8. グローバル状態方式への移行にあたっての影響範囲

### 優先度A（設計の根幹。ここが決まらないと実装に着手できない）

1. **`sigmaris_decision_log`との役割分担の確定**: 新設`sigmaris_global_state`と既存`sigmaris_decision_log`のどちらが「決定事項」の正とするかを先に決める。両立させるなら参照関係（`decision_refs`等）を明確化する。
2. **`chat_messages`（スレッド生ログ）と`recent_raw_turns`（グローバル状態内の直近ターン）の関係定義**: 二重管理を避けるため、「`chat_messages`はUI表示専用の生ログ、グローバル状態側は要約された`active_topics`のみを持つ」のように責務を切り分ける必要がある。
3. **同時書き込みの排他制御**: 現状`replace_chat_messages()`は楽観ロックなしの全置換方式。グローバル状態が単一行（ユーザーごとに1行）になると、同時に複数スレッドから会話が進行した場合の**書き込み競合が今よりも起きやすくなる**（現状はスレッドが違えば独立していたが、グローバル状態は全スレッド共有のため）。行レベルロックまたは楽観的並行性制御（`updated_at`/バージョン列でのCAS）の導入を検討する必要がある。
4. **フロントエンドとバックエンドの二重書き込み経路の統合**（0章・5章参照）: `frontend/src/lib/chat-threads.ts`（Next.js直接Supabase書き込み）と`backend/app/services/app_chat_data.py`（FastAPI経由）が同じテーブルに対して独立したロジックで書き込んでいる。グローバル状態導入時にどちらが正の更新経路になるかを決めないと、同期漏れが発生する。

### 優先度B（グローバル状態の質を左右するが、後追いでも対応可能）

5. **プロンプト組み立て順序の見直し**（7章）: グローバル状態注入時は「固定指示→可変コンテキスト」の順に並べ替え、キャッシュ効率を意識した設計にする。
6. **`_cognitive_layer_bg()`の記録内容の充実化**: 現状の空疎な`chat_turn:xxxx`ログを、グローバル状態更新の材料として使えるレベルの情報量に変更する。
7. **`LOCAL_LLM_ENABLED=false`時のRAG経路の扱い**: グローバル状態の検索にpgvector RAGを使うなら、現状のフラグ依存を見直し、常時有効にするか明示的にフォールバック戦略を決める。
8. **プロアクティブアクション（`proactive/actions.py`）の使い捨てthread_id**: グローバル状態方式に移行すれば、朝/夕/週次のプロアクティブ処理も同じグローバル状態を参照できるようになり、現状の「毎回独立したスレッド」という制約が解消される（これはグローバル状態方式のメリットとして明記できる）。

### 優先度C（将来的な改善）

9. `sigmaris_internal_state`のユーザー単位化（現状サービス全体で1行）。マルチユーザー展開時に必要。
10. `memory_bus.py`統一実装（`docs/sigmaris/memory_model.md`が既に提起しているConcept）。グローバル状態もこの統一APIの一部として設計すると将来の拡張がしやすい。

### そのまま流用できる部分

- `user_fact_items` / `user_fact_profile` / `user_fact_history`（Fact Memory）: 既にスレッド非依存のグローバル設計。移行対象に含める必要はなく、グローバル状態の一部として**そのまま参照するだけでよい**。
- `sigmaris_self_model`（Belief Memory）: 同上。
- `user_trend_items`（Trend Memory）: 同上。
- 非同期実行基盤（APScheduler + `asyncio.create_task`のfire-and-forgetパターン）: そのまま「応答後にグローバル状態を更新する」処理に流用できる（4章）。
- `memory_extractor.py`のfire-and-forget抽出パターン: グローバル状態への書き込みトリガーとして同じパターンを再利用できる。

### 置き換え・廃止を検討すべき部分

- `chat_messages`の全置換方式（`replace_chat_messages`）: グローバル状態方式でスレッドが「UIの入れ物」に徹するなら、差分アペンド方式への変更を検討する価値がある（現状の全削除→全INSERTは、スレッドが長くなるほど非効率かつ競合リスクが高い）。
- `sigmaris_decision_log`の現状の書き込み内容（`chat_turn:xxxx`という空疎なログ）: グローバル状態の`decisions_log`として意味を持たせるなら、現行の記録ロジックは実質的に作り直しが必要。
- フロントエンドの`chat-threads.ts`とバックエンドの`app_chat_data.py`のどちらか一方: 二重書き込み経路の統合にあたり、片方を薄いプロキシに縮小するか廃止する判断が必要。

---

## 9. 懸念点・リスク

1. **単一行グローバル状態のロック競合**: ユーザーごとに1行のJSONB列を複数スレッドから同時更新すると、PostgRESTのPATCHは基本的にlast-write-winsになりやすい。`updated_at`だけでは競合検知にならないため、バージョン列や`jsonb`のマージ戦略（部分更新RPC）を設計段階で決める必要がある。
2. **JSONB肥大化**: `decisions_log`/`active_topics`/`recent_raw_turns`を1行のJSONBに詰め込む設計は、行が肥大化するとPostgRESTの読み書きレイテンシが悪化する。件数上限・TTLベースの自動トリミング機構（`memory_validator.py`の減衰ロジックに近いもの）を最初から組み込むことを推奨。
3. **fire-and-forgetタスクの信頼性**: 現状のバックグラウンド更新（`memory_extractor`/`_cognitive_layer_bg`）は失敗時にログを吐くだけでリトライがない。グローバル状態がシステムの中核になるなら、この非同期更新の失敗がそのまま「グローバル状態が更新されない」という致命的な劣化につながる。最低限のリトライ・デッドレターログを検討すべき。
4. **既存のスレッド単位UI（フロントエンドのスレッド一覧・タイトル自動生成等）との整合**: `derive_thread_title()`はスレッド内の最初のユーザー発言から自動生成している。スレッドが単なる入れ物になっても、この機能自体は影響を受けないが、「スレッドタイトル」と「グローバル状態のactive_topics」が乖離した表示になるUX上の考慮が必要。
5. **移行の段階的実施**: 本調査で判明した通り、Fact Memory/Self Model/Trendは既に事実上グローバルな設計になっている。**全面的な作り直しではなく、「decision_log/experience_layerを本格稼働させ、chat_messagesとの責務を切り分ける」という段階的な移行の方がリスクが低い**と考えられる。

---

## Related Documents

- [cognitive_architecture.md](cognitive_architecture.md) — Memory Bus / Layer構成の設計思想
- [memory_model.md](memory_model.md) — 各Memory Typeの定義（本調査で参照した`sigmaris_decision_log`等の設計意図の原典）
- [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md) — 実装状況トラッキング（本調査時点でやや古い）
