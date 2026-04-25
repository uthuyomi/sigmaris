# Google 連携実装メモ

## 実装日

- 2026-03-28

## 実装内容

- `googleapis` を追加
- `openai` 公式 SDK を追加
- Google OAuth クライアント生成ヘルパーを追加
- Google Sheets URL を読み取るサーバー関数を追加
- Google Calendar に予定を書き込むサーバー関数を追加
- チャット API に `read_google_sheet` と `create_google_calendar_events` ツールを追加
- 設定画面に Google 連携状態表示を追加
- 取り込みプレビュー API と反映 API を追加

## 追加ファイル

- `src/lib/google/oauth.ts`
- `src/lib/google/sheets.ts`
- `src/lib/google/calendar.ts`
- `src/lib/import/schema.ts`
- `src/lib/import/extract.ts`
- `src/lib/openai/client.ts`
- `src/app/api/chat/route.ts`
- `src/app/api/import/preview/route.ts`
- `src/app/api/import/commit/route.ts`

## 必要な環境変数

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `GOOGLE_CALENDAR_ID`

`GOOGLE_REFRESH_TOKEN` のような共有 refresh token fallback は使わない。Google 操作はログイン済みユーザーの provider token に限定する。

## 現時点でできること

- チャット内で Google Sheets URL を扱うためのサーバー側取得基盤
- チャット指示から Google Calendar へ予定登録するためのサーバー側ツール
- 補助パネルからシートURLまたは画像を解析して予定候補一覧を作る
- 予定候補一覧から Google Calendar へ反映する

## まだ次段階のもの

- ユーザー単位の OAuth 接続
- 画像添付をそのままチャットスレッド本体へ流す transport
- 解析結果をチャット会話履歴へ自動注入する統合
