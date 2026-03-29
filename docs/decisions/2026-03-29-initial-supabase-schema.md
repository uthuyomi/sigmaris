# 2026-03-29 初期 Supabase スキーマを一括で切る

## 日付
- 2026-03-29

## 決定
- 初期スキーマは `profiles` `saved_locations` `calendar_connections` `import_jobs` `events` `event_travel_plans` の6テーブルで始める。
- RLS は最初から有効にする。
- `auth.users` 作成時に `profiles` を自動生成する。

## 理由
- 今のアプリ機能は、ユーザー、予定、取り込み、移動計画、外部カレンダー接続の5系統に分かれている。
- ここを最初から分けておくと、後で Google 連携や自前保存へ広げやすい。
- Supabase Auth を使う以上、`auth.users` と `profiles` の接続は最初に固めておく方が楽。

## 実装メモ
- SQL は `supabase/migrations/202603290001_initial_app_schema.sql`
- `default_grain_minutes` は `5 / 10 / 15 / 30 / 60` のみに制限
- `events` は `starts_at < ends_at` を DB 制約で守る
