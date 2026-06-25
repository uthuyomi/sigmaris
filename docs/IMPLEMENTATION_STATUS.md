# Sigmaris OS — 実装状況ドキュメント

最終更新: 2026-06-25

---

## 1. 実装済み機能一覧

### コア機能

| 機能名 | 実装ファイル | 概要 | 動作確認 | 主な環境変数 |
|---|---|---|---|---|
| チャット（ストリーミング） | `services/chat.py` (887行) | OpenAI APIを使ったストリーミングチャット。スレッド管理・メッセージ永続化・ツール呼び出しを含む中核機能。 | 確認済み | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| チャットルーティング | `services/chat_routing.py` (371行) | ユーザーの発話内容をカテゴリ分類し、適切なツール群・プロンプトに振り分ける。 | 確認済み | `OPENAI_API_KEY` |
| チャットツール | `services/chat_tools.py` (499行) | カレンダー操作・マップ検索・シートインポートなどのツール実行ハンドラ群。 | 確認済み | Google系キー一式 |
| チャットツール定義 | `services/chat_tool_definitions.py` (214行) | OpenAI function calling スキーマ定義。 | 確認済み | — |
| チャットメッセージ管理 | `services/chat_messages.py` (71行) | Supabase上のチャットスレッド・メッセージのCRUD。 | 確認済み | Supabase設定 |
| チャット添付ファイル | `services/chat_attachments.py` (99行) | チャットに添付される画像・ファイルの処理。 | 確認済み | — |
| プロンプト管理 | `services/chat_prompts.py` (81行) | システムプロンプトの組み立て・ユーザープロフィール注入。 | 確認済み | — |

### Google連携

| 機能名 | 実装ファイル | 概要 | 動作確認 | 主な環境変数 |
|---|---|---|---|---|
| Google Calendar | `services/google_calendar.py` (148行) | カレンダーイベントの取得・作成・削除・範囲削除。OAuth認証トークンを直接受け取る設計。 | 確認済み | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_CALENDAR_ID` |
| Google Maps（コア） | `services/google_maps_core.py` (116行) | Places API・Geocoding APIの基盤クライアント。 | 確認済み | `GOOGLE_MAPS_API_KEY` |
| Google Maps（ルート） | `services/google_maps_routes.py` (166行) | Routes APIを使った経路計算（徒歩・電車・車・自転車）。 | 確認済み | `GOOGLE_MAPS_API_KEY` |
| Google Maps（場所） | `services/google_maps_locations.py` (74行) | 保存済み場所の検索・周辺施設の検索。 | 確認済み | `GOOGLE_MAPS_API_KEY` |
| Google Sheets取込 | `services/google_sheets.py` (51行) | Sheets APIからデータを取得してインポートジョブに変換。 | 確認済み | Google OAuth設定 |
| Google共通クライアント | `services/google_api.py` (39行) | Googleトークンリフレッシュ・認証ヘッダー構築の共通処理。 | 確認済み | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| モビリティ計画 | `services/` + `routes/mobility.py` | 出発地〜目的地の移動計画をルート計算結果から生成。 | 確認済み | `GOOGLE_MAPS_API_KEY` |

### アプリデータ

| 機能名 | 実装ファイル | 概要 | 動作確認 | 主な環境変数 |
|---|---|---|---|---|
| イベントデータ | `services/app_event_data.py` (321行) | イベントの検索・作成・更新・削除。監査ログ付きRPC経由で書き込み。 | 確認済み | Supabase設定 |
| プロフィールデータ | `services/app_profile_data.py` (76行) | ユーザープロフィールの取得・更新。 | 確認済み | Supabase設定 |
| チャットデータ | `services/app_chat_data.py` (99行) | チャットスレッド・メッセージの取得・置換。 | 確認済み | Supabase設定 |
| インポートプレビュー | `services/import_extract.py` (98行) | CSVやシートデータをイベント形式にパースしてプレビュー表示。 | 確認済み | — |
| ビリング | `services/billing.py` (70行) | Stripe連携のサブスクリプション管理・プラン確認。 | 確認済み | Stripe設定（env未記載） |

### 統括エージェント（オーケストレーター）層

| 機能名 | 実装ファイル | 概要 | 動作確認 | 主な環境変数 |
|---|---|---|---|---|
| オーケストレーターサービス | `services/orchestrator/service.py` (162行) | ユーザーリクエストを受けて監査ログ・プロフィール・自己モデルを取得し、スケジュールエージェントに委譲して結果を人格層で整形する全体調整役。 | 確認済み | 各種設定一式 |
| スケジュールエージェントクライアント | `services/orchestrator/schedule_agent_client.py` (110行) | 外部スケジュールエージェントへのHTTP呼び出し。system_override（ユーザープロフィール＋自己モデル）を注入。 | 確認済み | `SCHEDULE_AGENT_BASE_URL`, `SCHEDULE_AGENT_SECRET` |
| 人格リライター | `services/orchestrator/persona_rewriter.py` (119行) | スケジュールエージェントの機械的な出力をpersona.mdに基づいてシグマリスの口調に変換。 | 確認済み | `OPENAI_API_KEY`, `SIGMARIS_PERSONA_PATH` |
| レスポンスガード | `services/orchestrator/response_guard.py` (148行) | リライト後の応答が機械的事実（日時・数値・URL）を保持しているか機械的＋AI的に検証。 | 確認済み | `OPENAI_API_KEY` |
| 人格ローダー | `services/orchestrator/persona_loader.py` (45行) | persona.mdをハッシュ付きで読み込み。変更検知に対応。 | 確認済み | `SIGMARIS_PERSONA_PATH` |
| エージェントレジストリ | `services/orchestrator/agent_registry.py` (22行) | スケジュールエージェントの接続先定義。 | 確認済み | `SCHEDULE_AGENT_BASE_URL`, `SCHEDULE_AGENT_ID` |
| 監査ログ（オーケストレーター） | `services/orchestrator/audit.py` (68行) | エージェント呼び出しの開始・終了をDBに記録。 | 確認済み | Supabase設定 |

### Sigmaris AIレイヤー

| 機能名 | 実装ファイル | 概要 | 動作確認 | 主な環境変数 |
|---|---|---|---|---|
| 事実記憶層 | `services/user_fact_data.py` (138行) | ユーザーの事実（名前・習慣・目標など）をカテゴリ・キーで管理。信頼度・ソース付き。RPC経由でupsert。 | デプロイ待ち | Supabase設定（`SUPABASE_SERVICE_ROLE_KEY`） |
| 自己モデル | `services/self_model.py` (273行) | シグマリス自身の自己認識（identity/goals/patterns）をDB管理。反省処理でOpenAI分析→自己更新→乖離記録まで行う。 | デプロイ待ち | `SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_API_KEY`, `SIGMARIS_REFLECT_MODEL` |
| 自律プロアクティブ通知 | `services/proactive/` (4ファイル, 310行) | APSchedulerで朝8時・夜22時・日曜20時に自動実行。オーケストレーターを呼び出してPushoverで通知。 | 未確認 | `PROACTIVE_ENABLED`, `PUSHOVER_APP_TOKEN`, `PUSHOVER_USER_KEY` |
| JWTオートリフレッシュ | `services/proactive/jwt_manager.py` (146行) | Supabaseリフレッシュトークンを使いアクセストークンを期限切れ5分前に自動更新。ローテーション対応。asyncio.Lock使用。 | 未確認 | `SIGMARIS_USER_JWT`, `SIGMARIS_REFRESH_TOKEN` |
| 自己改良エージェント | `services/self_improvement.py` (354行) | 監査ログを分析して改善提案を生成。persona.mdは直接更新、コード変更はGitHub PRとして作成（直接pushなし）。.env等の認証ファイルへの変更は拒否。 | 未確認 | `SELF_IMPROVEMENT_ENABLED`, `GITHUB_TOKEN`, `GITHUB_REPO` |
| ローカルLLM統合 | `services/local_llm.py` (165行) | OllamaとOpenAI APIを切り替えるルーター。ROUTING/MEMORY_EXTRACTION/SELF_REFLECT/SUMMARIZEをローカルへ、COMPLEX_REASONINGをOpenAIへ。起動失敗時は自動フォールバック。 | 未確認 | `LOCAL_LLM_ENABLED`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |

### X (Twitter)連携

| 機能名 | 実装ファイル | 概要 | 動作確認 | 主な環境変数 |
|---|---|---|---|---|
| X投稿 | `services/x_publisher.py` (196行) | Twitter API v2 + OAuth 1.0aで投稿。post_type別フォーマット（daily_log/milestone/observation/self_reflection）。X_ENABLED=falseならLogPublisherにフォールバック。 | 未確認 | `X_ENABLED`, `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` |
| X返信分類 | `services/x_reply_classifier.py` (127行) | 返信テキストをHIGH/MEDIUM/LOWに分類（LLMRouter=ROUTINGタスク）。HIGH/MEDIUMのみ返信文を生成（COMPLEX_REASONINGタスク）。140文字制限。 | 未確認 | （LLM設定を流用） |

### ヘルスデータ

| 機能名 | 実装ファイル | 概要 | 動作確認 | 主な環境変数 |
|---|---|---|---|---|
| Google Fitデータ取得 | `services/health_data.py` (262行) | Google Fit Aggregate APIで1日の歩数・心拍数（安静時+平均）・カロリー・睡眠（時間+品質good/fair/poor）を取得。user_fact_itemsにconfidence=0.9/source=sensorで記録。 | 未確認 | `HEALTH_SYNC_ENABLED`、Google OAuthトークン（実行時渡し） |

---

## 2. エンドポイント一覧

### チャット系 `/api/chat/`

| メソッド | パス | 認証 | 概要 |
|---|---|---|---|
| `GET` | `/api/chat/capabilities` | JWT | 利用可能なツール一覧を返す |
| `POST` | `/api/chat/stream` | JWT | ストリーミングチャット。ツール呼び出しも処理 |

### オーケストレーター系 `/api/orchestrator/`

| メソッド | パス | 認証 | 概要 |
|---|---|---|---|
| `POST` | `/api/orchestrator/chat` | JWT | 人格統括エージェント経由のチャット。プロフィール・自己モデル・persona.mdを統合 |

### アプリデータ系 `/api/app/`

| メソッド | パス | 認証 | 概要 |
|---|---|---|---|
| `POST` | `/api/app/events/search` | JWT | イベント検索 |
| `GET` | `/api/app/home-context` | JWT | ホーム画面用コンテキスト（今日の予定・残タスク等） |
| `GET` | `/api/app/chat/threads/{thread_id}` | JWT | チャットスレッド取得 |
| `POST` | `/api/app/chat/messages/replace` | JWT | チャットメッセージ一括置換 |

### Googleツール系 `/api/google/`

| メソッド | パス | 認証 | 概要 |
|---|---|---|---|
| `POST` | `/api/google/calendar/list` | JWT | Googleカレンダーイベント一覧取得 |
| `POST` | `/api/google/calendar/create` | JWT | カレンダーイベント作成（監査ログ付き） |
| `POST` | `/api/google/calendar/delete` | JWT | カレンダーイベント削除 |
| `POST` | `/api/google/calendar/delete-range` | JWT | 期間指定での一括削除 |
| `POST` | `/api/google/sheets/preview` | JWT | Sheetsデータのプレビュー取得 |

### モビリティ系 `/api/mobility/`

| メソッド | パス | 認証 | 概要 |
|---|---|---|---|
| `POST` | `/api/mobility/plan` | JWT | 経路計画（出発地・目的地・移動手段） |

### インポート系 `/api/import/`

| メソッド | パス | 認証 | 概要 |
|---|---|---|---|
| `POST` | `/api/import/preview` | JWT | CSVまたはシートデータのイベントプレビュー |

### エージェント間インターフェース `/api/agent/`

| メソッド | パス | 認証 | 概要 |
|---|---|---|---|
| `POST` | `/api/agent/chat/complete` | エージェント＋JWT | エージェント間チャット補完呼び出し |
| `POST` | `/api/agent/tools/execute` | エージェント＋JWT | ツール実行（カレンダー・マップ等） |
| `GET` | `/api/agent/facts/profile` | エージェント＋JWT | ユーザー事実プロフィール取得 |
| `GET` | `/api/agent/facts/items` | エージェント＋JWT | 事実アイテム一覧（category絞り込み可） |
| `POST` | `/api/agent/facts/items` | エージェント＋JWT | 事実アイテムのupsert |
| `GET` | `/api/agent/facts/unknown` | エージェント＋JWT | 未記録フィールド一覧 |
| `POST` | `/api/agent/proactive/trigger` | JWTのみ | プロアクティブアクション手動トリガー（morning_briefing/evening_checkin/weekly_review） |
| `GET` | `/api/agent/self/model` | エージェント | 自己モデル取得 |
| `POST` | `/api/agent/self/model` | エージェント | 自己モデル更新 |
| `POST` | `/api/agent/self/discrepancy` | エージェント | 行動乖離の記録 |
| `POST` | `/api/agent/self/reflect` | エージェント | 自己反省実行（監査ログ分析→自己モデル更新） |
| `POST` | `/api/agent/self/improve` | エージェント | 自己改良提案の生成 |
| `POST` | `/api/agent/self/apply` | エージェント | 自己改良提案の適用（persona更新 or GitHub PR作成） |
| `POST` | `/api/agent/x/classify` | エージェント | X返信のHIGH/MEDIUM/LOW分類 |
| `POST` | `/api/agent/x/respond` | エージェント | X返信文の生成 |
| `POST` | `/api/agent/health/sync` | エージェント＋JWT | 今日のGoogle Fitデータ取得→事実記憶保存 |
| `GET` | `/api/agent/health/summary` | エージェント＋JWT | 直近7日間の健康データサマリー |

---

## 3. 環境変数一覧

| 変数名 | 必須/任意 | デフォルト | 説明 |
|---|---|---|---|
| `APP_ENV` | 任意 | `development` | 実行環境（`production` / `development`） |
| `API_PREFIX` | 任意 | `/api` | APIパスプレフィックス |
| `FRONTEND_ORIGIN` | 必須 | `http://localhost:3000` | CORSで許可するフロントエンドオリジン |
| `NEXT_PUBLIC_SUPABASE_URL` | 必須 | — | SupabaseプロジェクトURL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | 必須 | — | Supabase anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | 必須（自己モデル系） | — | Supabase service_role key。RLSバイパスが必要な自己モデル操作に使用 |
| `OPENAI_API_KEY` | 必須 | — | OpenAI APIキー |
| `OPENAI_MODEL` | 任意 | `gpt-5-nano` | チャット・統括で使用するモデル |
| `OPENAI_IMPORT_MODEL` | 任意 | — | インポート処理専用モデル（未指定時はOPENAI_MODEL） |
| `GOOGLE_CLIENT_ID` | 必須 | — | Google OAuth クライアントID |
| `GOOGLE_CLIENT_SECRET` | 必須 | — | Google OAuth クライアントシークレット |
| `GOOGLE_REDIRECT_URI` | 必須 | — | Google OAuth リダイレクトURI |
| `GOOGLE_CALENDAR_ID` | 任意 | `primary` | 操作対象Googleカレンダーのアカウント |
| `GOOGLE_MAPS_API_KEY` | 必須 | — | Google Maps Platform APIキー |
| `AGENT_SECRETS` | 必須 | — | エージェント認証用シークレットのJSON辞書（例: `{"sigmaris-orchestrator":"secret"}`） |
| `SCHEDULE_AGENT_BASE_URL` | 任意 | `http://127.0.0.1:8000` | スケジュールエージェントのベースURL |
| `SCHEDULE_AGENT_ID` | 任意 | `sigmaris-orchestrator` | スケジュールエージェントのエージェントID |
| `SCHEDULE_AGENT_SECRET` | 必須 | — | スケジュールエージェントへの認証シークレット |
| `SIGMARIS_PERSONA_PATH` | 任意 | `../docs/persona.md` | persona.mdファイルの相対パス（backendディレクトリからの相対） |
| `SIGMARIS_REWRITE_MODEL` | 任意 | — | 人格リライト専用モデル（未指定時はOPENAI_MODEL） |
| `SIGMARIS_GUARD_MODEL` | 任意 | — | レスポンスガード専用モデル（未指定時はOPENAI_MODEL） |
| `SIGMARIS_REFLECT_MODEL` | 任意 | — | 自己反省・ヘルス分析専用モデル（未指定時はOPENAI_MODEL） |
| `SIGMARIS_TIMEZONE` | 任意 | `Asia/Tokyo` | プロアクティブスケジューラのタイムゾーン |
| `SIGMARIS_USER_JWT` | 任意 | — | プロアクティブアクション実行用の初期アクセストークン（起動時のみ使用） |
| `SIGMARIS_REFRESH_TOKEN` | 任意 | — | JWTオートリフレッシュ用Supabaseリフレッシュトークン |
| `SIGMARIS_LAUNCH_DATE` | 任意 | — | 起動日（YYYY-MM-DD）。X投稿の「起動N日目」カウンターに使用 |
| `PUSHOVER_USER_KEY` | 任意 | — | Pushoverユーザーキー。未設定時はLogNotifierにフォールバック |
| `PUSHOVER_APP_TOKEN` | 任意 | — | Pushoverアプリトークン |
| `PROACTIVE_ENABLED` | 任意 | `true` | プロアクティブスケジューラの有効/無効 |
| `LOCAL_LLM_ENABLED` | 任意 | `false` | Ollama（ローカルLLM）の有効/無効 |
| `OLLAMA_BASE_URL` | 任意 | `http://localhost:11434` | OllamaサーバーのベースURL |
| `OLLAMA_MODEL` | 任意 | `qwen2.5:14b` | Ollamaで使用するモデル名 |
| `X_API_KEY` | 任意 | — | Twitter API v2 APIキー |
| `X_API_SECRET` | 任意 | — | Twitter API v2 APIシークレット |
| `X_ACCESS_TOKEN` | 任意 | — | Twitter OAuth 1.0a アクセストークン |
| `X_ACCESS_TOKEN_SECRET` | 任意 | — | Twitter OAuth 1.0a アクセストークンシークレット |
| `X_ENABLED` | 任意 | `false` | X投稿機能の有効/無効 |
| `SELF_IMPROVEMENT_ENABLED` | 任意 | `false` | 自己改良エージェントの有効/無効 |
| `GITHUB_TOKEN` | 任意 | — | GitHub PR作成用パーソナルアクセストークン |
| `GITHUB_REPO` | 任意 | — | GitHub リポジトリ（`owner/repo` 形式） |
| `HEALTH_SYNC_ENABLED` | 任意 | `false` | Google Fitヘルスデータ同期の有効/無効 |

---

## 4. データベーステーブル一覧

| テーブル名 | 用途 | RLS | マイグレーション |
|---|---|---|---|
| `profiles` | ユーザープロフィール（名前・ロケール・AIトーン設定・テーマ等） | 有効（本人のみ） | `202603290001` + 各ALTERパッチ |
| `saved_locations` | 保存済み場所（自宅・職場等） | 有効（本人のみ） | `202603290001` |
| `calendar_connections` | Googleカレンダー接続情報 | 有効（本人のみ） | `202603290001` |
| `import_jobs` | データインポートジョブ管理 | 有効（本人のみ） | `202603290001` |
| `events` | カレンダーイベント | 有効（本人のみ） | `202603290001` |
| `event_travel_plans` | イベントに紐づく移動計画 | 有効（本人のみ） | `202603290001` + `202603310006`, `202604010007` |
| `chat_threads` | チャットスレッド | 有効（本人のみ） | `202603290003` |
| `chat_messages` | チャットメッセージ | 有効（本人のみ） | `202603290003` |
| `push_subscriptions` | プッシュ通知サブスクリプション（Web Push） | 有効（本人のみ） | `202605080012` |
| `travel_notification_deliveries` | 移動通知の配信履歴 | 有効（本人のみ） | `202605080012` |
| `billing_customers` | Stripeカスタマー情報 | 有効（本人のみ） | `202605080013` |
| `subscriptions` | サブスクリプション状態 | 有効（本人のみ） | `202605080013` |
| `event_audit_logs` | イベント操作の監査ログ | 有効（本人のみ） | `202606200014` |
| `agent_invocation_audit_logs` | エージェント呼び出しの監査ログ | 有効（本人のみ） | `202606210015` |
| `user_fact_profile` | ユーザー事実プロフィール（スカラー値） | 有効（本人のみ） | `202606240016` |
| `user_fact_items` | ユーザー事実アイテム（カテゴリ・キー・値） | 有効（本人のみ） | `202606240016` |
| `user_fact_history` | 事実アイテムの変更履歴 | 有効（本人のみ） | `202606240016` |
| `sigmaris_self_model` | シグマリス自己モデル（シングルトン行） | 有効（service_roleのみ・ユーザーポリシーなし） | `202606250017` ⚠️未適用 |
| `sigmaris_self_discrepancies` | シグマリスの行動乖離記録 | 有効（service_roleのみ・ユーザーポリシーなし） | `202606250017` ⚠️未適用 |

> ⚠️ `202606250017_sigmaris_self_model.sql` はコミット済みだがSupabase Dashboardでの手動適用が必要。

---

## 5. コード規模

実際にカウントした行数（2026-06-25時点）:

| 区分 | ファイル数 | 行数 |
|---|---|---|
| バックエンド全体 (`backend/app/`) | 58 `.py` | **7,632行** |
| サービス層 (`backend/app/services/`) | 43 `.py` | **6,280行** |
| ルーター層 (`backend/app/routes/`) | 8 `.py` | **1,033行** |
| スキーマ層 (`backend/app/schemas/`) | 4 `.py` | **185行** |
| フロントエンド (`frontend/src/`) | 157 `.ts/.tsx` | **14,316行** |
| マイグレーション (`supabase/migrations/`) | 17 `.sql` | **1,016行** |

### サービスファイル別行数（主要なもの）

| ファイル | 行数 |
|---|---|
| `chat.py` | 887 |
| `chat_routing.py` | 371 |
| `self_improvement.py` | 354 |
| `chat_tools.py` | 499 |
| `chat_tool_definitions.py` | 214 |
| `app_event_data.py` | 321 |
| `self_model.py` | 273 |
| `health_data.py` | 262 |
| `x_publisher.py` | 196 |
| `orchestrator/service.py` | 162 |
| `local_llm.py` | 165 |
| `google_maps_routes.py` | 166 |
| `orchestrator/response_guard.py` | 148 |
| `proactive/jwt_manager.py` | 146 |
| `google_calendar.py` | 148 |
| `x_reply_classifier.py` | 127 |
| `orchestrator/persona_rewriter.py` | 119 |
| `orchestrator/schedule_agent_client.py` | 110 |

---

## 6. 未実装・今後の実装予定

### Phase 1（近期）

- **X Webhook受信**: X返信を自動受信してXReplyClassifierで処理→自動返信する基盤。現在は分類・返信生成の関数は実装済みだが、Webhookエンドポイントが未実装。
- **ヘルスデータのGoogle Fit OAuthスコープ追加**: 現在の `google_api.py` のスコープにFitness APIを追加する必要あり。
- `sigmaris_self_model` テーブルの適用とシードデータ投入（Dashboard手動作業）。

### Phase 2（中期）

- **定期自己反省のcronスケジュール化**: `reflect()` は手動トリガー（`/api/agent/self/reflect`）のみ。週次で自動実行するAPSchedulerジョブの追加。
- **自己改良の自動サイクル**: `self/improve` → 人間レビュー → `self/apply` のワークフローUI。
- **LLMRouter本番稼働**: `LOCAL_LLM_ENABLED=true` でのOllama実運用検証。Ollama未起動時のフォールバック動作確認。
- **事実記憶の自動抽出**: 会話ログからuser_fact_itemsを自動更新するパイプライン（`MEMORY_EXTRACTION`タスクタイプ定義済み）。

### Phase 3（将来）

- **Pixel Watch 2ネイティブ連携**: Google Fitへの依存からWear OS/Health Connect APIへの移行。
- **マルチユーザー対応の自己モデル**: 現在のシングルトンモデルをユーザー別に拡張。
- **フロントエンドでの健康データ表示**: `/api/agent/health/summary` をUIに接続。
- **X投稿スケジュール管理**: 時間帯指定の投稿キュー。

---

## 7. 既知の問題・注意事項

### デプロイ待ち・手動作業が必要な項目

1. **`supabase/migrations/202606250017_sigmaris_self_model.sql`**
   - Supabase Dashboard → SQL Editor で手動実行が必要
   - 適用後に `supabase/seeds/seed_self_model.sql` も実行すること

2. **`supabase/migrations/202606240016_fact_memory.sql`**
   - 直近で追加されたファクトメモリ層のマイグレーション。適用済みか確認すること

### 動作確認が必要な箇所

- **プロアクティブスケジューラ**: `SIGMARIS_USER_JWT` と `SIGMARIS_REFRESH_TOKEN` の両方を設定しないとJWT取得で失敗する。`PROACTIVE_ENABLED=true` でも実際の通知はPushoverキー設定が必要。
- **自己改良エージェント**: `SELF_IMPROVEMENT_ENABLED=false` がデフォルト。PR作成機能は `GITHUB_TOKEN` と `GITHUB_REPO` が未設定の場合スキップ（エラーにならず `skipped` を返す）。
- **X投稿の朝ブリーフィング統合**: `run_morning_briefing()` 成功後にX投稿を試みるが、`X_ENABLED=false` の場合はLogPublisherがログ出力のみ行う。本番でX投稿を有効にする前に必ずテスト投稿で確認すること。
- **ヘルスデータ同期**: `X-Google-Access-Token` ヘッダーにFitness APIスコープを持つトークンが必要。現在のOAuthフロー（`google_api.py`）がFitnessスコープを含むか確認すること。

### 設定が必要な環境変数（本番稼働前）

| 変数 | 理由 |
|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | 自己モデル・ファクトメモリのサービスロール操作に必須 |
| `SIGMARIS_USER_JWT` + `SIGMARIS_REFRESH_TOKEN` | プロアクティブアクション実行に必須 |
| `PUSHOVER_APP_TOKEN` + `PUSHOVER_USER_KEY` | プロアクティブ通知の実送信に必須 |
| `GITHUB_TOKEN` + `GITHUB_REPO` | 自己改良のコードPR作成に必須 |
| `X_API_KEY` 他4変数 | X投稿・返信機能の実運用に必須 |
| `SIGMARIS_LAUNCH_DATE` | X投稿の「起動N日目」カウンターに必要 |
