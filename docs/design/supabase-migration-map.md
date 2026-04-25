# Supabase Migration Map

## 目的

このページは、Supabase の migration と、実際にアプリのどの機能に効いているかを対応づけるためのものだよ。  
会話ログでは段階的に schema が育っているので、後から見ると「どの migration を流せばどこが直るのか」が分かる形にしておく。

## Migration 一覧

### `202603290001_initial_app_schema.sql`

主な内容:

- `profiles`
- `saved_locations`
- `calendar_connections`
- `import_jobs`
- `events`
- `event_travel_plans`
- `updated_at` trigger
- 基本的な RLS

効く機能:

- 自前予定 DB
- 保存地点
- 移動ブロック
- import 管理

### `202603290002_google_calendar_sync.sql`

主な内容:

- Google Calendar 双方向同期に必要なカラム追加
- 外部 event との紐付け用情報

効く機能:

- Google からアプリへの取り込み
- アプリから Google への送信
- 同期状態の保持

### `202603290003_chat_threads.sql`

主な内容:

- `chat_threads`
- `chat_messages`
- chat 用 index
- chat 用 RLS

効く機能:

- スレッド一覧
- 過去会話の再開
- スレッド名変更
- スレッド削除
- message 永続化

### `202603290004_profile_locale.sql`

主な内容:

- `profiles.locale`

効く機能:

- UI 言語切り替え
- ロケール保存

### `202603300005_profile_ai_tone.sql`

主な内容:

- `profiles.ai_tone`

効く機能:

- AI 口調切り替え
- backend chat system prompt のトーン制御

### `202603310006_profile_preferred_travel_mode.sql`

主な内容:

- `profiles.preferred_travel_mode`
- `event_travel_plans.travel_mode` 制約拡張

効く機能:

- 既定の移動手段設定
- mobility panel の初期値
- chat による移動手段補完

### `202604010007_travel_plan_route_metrics.sql`

主な内容:

- `event_travel_plans.fare_text`
- `event_travel_plans.fare_amount`
- `event_travel_plans.fare_currency`
- `event_travel_plans.transfer_count`
- `event_travel_plans.walking_distance_meters`
- `event_travel_plans.walking_duration_minutes`
- `event_travel_plans.selected_candidate`

効く機能:

- 公共交通候補の価格順比較
- 徒歩量 / 乗換回数の保存
- 選ばれた route 候補の保存
- AI と UI の両方からの travel block 反映

### `202604010008_profile_arrival_lead_minutes.sql`

主な内容:

- `profiles.arrival_lead_minutes`

効く機能:

- 予定開始の何分前に到着したいかの設定
- 1分単位の到着余裕時間調整
- mobility と AI の route 探索基準時刻

## 実務上の見方

エラーが出た時は、まず「参照している列が migration 適用済みか」を見るのが早い。  
たとえば過去に起きた `profiles.locale does not exist` は、この対応表で見ると `202603290004_profile_locale.sql` が未適用だとすぐ分かる。

## 新しい migration を足す時のルール

- 1テーマ1 migration を基本にする
- 追加したら、このページにも追記する
- `どの UI / backend / sync に効くか` を必ず一緒に書く

## Notion へ移す時のおすすめ

Notion では `データモデル` 親ページの下に、

- スキーマ概要
- migration 対応表
- 運用メモ

を置くと追いやすい。  
このページは、その中の `migration 対応表` としてそのまま使えるよ。
