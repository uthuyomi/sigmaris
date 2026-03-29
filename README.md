# ShiftPilotAI

ShiftPilotAI は、チャットで予定を組みながら、カレンダー、タイムライン、外部連携をまとめて扱うための実験用アプリだよ。  
Markdown のままでも読めるし、あとで Notion に移しやすい構成でドキュメントを整理している。

## ドキュメント入口
- [docs/README.md](/d:/souce/ShiftPilotAI/docs/README.md)
- [docs/project-overview.md](/d:/souce/ShiftPilotAI/docs/project-overview.md)
- [docs/requirements/README.md](/d:/souce/ShiftPilotAI/docs/requirements/README.md)
- [docs/design/README.md](/d:/souce/ShiftPilotAI/docs/design/README.md)
- [docs/decisions/README.md](/d:/souce/ShiftPilotAI/docs/decisions/README.md)
- [docs/operations/README.md](/d:/souce/ShiftPilotAI/docs/operations/README.md)

## 現在の構成
- フレームワーク: `Next.js`
- 言語: `TypeScript`
- UI: `Tailwind CSS`
- チャット: `assistant-ui`
- AI 連携: `OpenAI`
- 認証: `Supabase Auth + Google OAuth`
- 外部連携: `Google Sheets` `Google Calendar` `Google Maps`

## 開発コマンド
- 開発サーバー: `npm run dev`
- Lint: `npm run lint`
- 本番ビルド: `npm run build`

## 必要な環境変数
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_IMPORT_MODEL`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `GOOGLE_CALENDAR_ID`
- `GOOGLE_MAPS_API_KEY`
- `HOME_ADDRESS`
- `NEXT_PUBLIC_HOME_ADDRESS`

## こちらで用意したもの
- Supabase SSR 用のクライアントと `proxy.ts`
- `/auth/callback` と `/auth/signout`
- Google OAuth ログイン UI
- Google の provider token を使う Calendar / Sheets 連携の土台

## こちらで用意してほしいもの
1. Supabase プロジェクト
2. Supabase の `Google` プロバイダ設定
3. Google Cloud の OAuth クライアント
4. `.env.local` への環境変数設定

## 準備メモ
1. Supabase Dashboard で `Authentication -> Providers -> Google` を有効にする。
2. Google Cloud Console で OAuth クライアントを作り、Supabase が案内するコールバック URL を登録する。
3. Supabase 側の Redirect URL に `http://localhost:3000/auth/callback` を追加する。
4. `.env.local` に `.env.example` の値を入れる。
5. 開発中は `http://localhost:3000` で Google ログインを試す。

## 実装メモ
- カレンダーで日付を選び、その日のタイムラインで時間を詰める構成。
- 予定粒度は `5 / 10 / 15 / 30 / 60分` を切り替え可能。
- チャット起点で Google Sheets URL と画像ファイルを取り込み、予定候補へ変換する。
- Google Calendar への登録と、Google Maps を使った移動計画の表示に対応している。

## ドキュメント運用
- 決定事項は `docs/decisions/`
- 設計意図は `docs/design/`
- 作業の流れは `docs/operations/`

Notion へ移すときも、この単位のままページを分ければ持ち運びしやすいってわけさ。
