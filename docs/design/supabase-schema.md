# Supabase Schema

## 目的
- 今のアプリ機能を支える最小限のテーブルをまとめて用意する。
- 後から Notion や実装コードに引きずられず、DB の責務をはっきりさせる。

## 今回の一括スキーマ
- `profiles`
  - ユーザー基本情報
  - デフォルト粒度
  - 自宅住所
- `saved_locations`
  - 自宅、職場、よく使う出発地
- `calendar_connections`
  - Google などのカレンダー接続先
- `import_jobs`
  - シートや画像からの取り込み記録
- `events`
  - 予定本体
- `event_travel_plans`
  - 予定に紐づく移動計画

## 置き場所
- `supabase/migrations/202603290001_initial_app_schema.sql`

## 含めたもの
- 主キー
- 外部キー
- `created_at` / `updated_at`
- `updated_at` 自動更新トリガー
- `auth.users` から `profiles` を作るトリガー
- RLS
- ユーザー本人だけ見えるポリシー

## ねらい
- 今の UI と API に必要な保存先を先に揃える
- Google Calendar 連携と自前イベントを同じ `events` に寄せる
- 取り込みと移動計画も後で結び直しやすくする

## 次の実装候補
- `calendar_connections` へ実際の Google 接続情報を保存
- `events` を Supabase から読むように UI を差し替え
- 取り込み結果を `import_jobs` と `events` へ保存
