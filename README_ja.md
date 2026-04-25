# ShiftPilotAI

ShiftPilotAI は、シフト表のスクリーンショット、Google Sheets、チャットでの指示から予定候補を作り、確認してから Google Calendar に保存できる AI スケジューリングアプリです。場所がある予定については、移動時間や出発時刻も計算し、移動ブロックとして予定に追加できます。

フロントエンドは Next.js、バックエンドは FastAPI、認証とデータベースは Supabase、AI 処理は OpenAI、外部連携は Google Calendar / Sheets / Maps を使っています。

> ステータス: 開発中のアクティブなプロトタイプです。主要なワークフローは実装済みですが、完成済みのホスト型プロダクトではありません。

[English README](./README.md)

---

## なぜ作ったか

シフト表を毎回カレンダーへ手入力する作業は地味に面倒です。さらに、予定ごとに場所、移動時間、出発時刻まで考える必要があると、単なる予定入力では済まなくなります。

ShiftPilotAI は、次の流れを短くすることを目的にしています。

1. シフト表画像、Google Sheets URL、予定メモを送る。
2. AI が予定候補を抽出する。
3. タイトル、日付、開始時刻、終了時刻を確認する。
4. 確認した予定を Google Calendar に保存する。
5. 場所がある予定について、移動時間と出発時刻を計算する。
6. 月カレンダーや日別タイムラインで全体を確認する。

目指しているのは、汎用カレンダー UI ではありません。シフト、予定、場所、移動時間まわりの「毎回やる整理作業」を減らすための道具です。

---

## 主な機能

### AI 予定取り込み

- シフト表のスクリーンショットや写真から予定候補を抽出。
- Google Sheets URL から予定に使える行を読み取り。
- タイトル、日付、開始時刻、終了時刻、説明、信頼度を持つ候補データを生成。
- 保存前に確認ステップを挟む設計。

### チャット起点の予定調整

- チャットで予定、既存イベント、移動について相談。
- スレッド単位で会話を保存。
- スレッド名の変更と削除。
- ユーザーの依頼内容に応じて backend 側で利用ツールを切り替え。
- アプリ内予定や Google Calendar の情報を参照して返答。

### Google Calendar 連携

- Supabase Auth 経由で Google ログイン。
- Google Calendar の予定読み取り。
- 確認済み予定の Google Calendar 登録。
- Google Calendar の予定をアプリ DB へ同期。
- 移動ブロックを作成し、必要に応じて Google Calendar にも保存。

### Google Sheets 連携

- Google Sheets URL からスプレッドシート ID を抽出。
- 先頭シートのプレビュー行を取得。
- 行データを AI 抽出パイプラインに渡して予定候補を生成。

### 移動計画

- Google Maps を使った経路計算。
- 対応モード: 車、自転車、徒歩。
- 自宅、保存済み地点、カスタム地点を出発地に指定。
- 予定開始時刻と「何分前に到着したいか」の設定から推奨出発時刻を計算。
- 移動予定を目的地の予定に紐づくイベントとして保存。

現在の制約: 公共交通機関の経路検索は未対応です。バスや電車の候補比較は現時点では行いません。

### カレンダーとタイムライン

- 月表示カレンダー。
- 日別タイムライン。
- アプリ作成予定と Google 同期予定の表示。
- チャット、カレンダー、タイムライン、設定を持つアプリシェル。

### ユーザー設定

- 表示言語。
- AI の返答トーン。
- 既定の移動手段。
- 到着余裕時間。
- 自宅住所と保存済み地点。
- Google Calendar 同期 ON/OFF。

対応表示言語:

- 日本語
- 英語
- 韓国語
- 中国語 簡体字
- 中国語 繁体字
- スペイン語
- フランス語
- ドイツ語
- ポルトガル語 ブラジル
- イタリア語
- インドネシア語
- タイ語
- ベトナム語

---

## 技術スタック

### フロントエンド

- Next.js 16
- React 19
- TypeScript
- Tailwind CSS
- assistant-ui
- Supabase SSR client
- Google APIs Node client
- Zod

### バックエンド

- FastAPI
- Python 3.12+
- OpenAI Responses API
- Google API Python client
- ユーザー JWT による Supabase REST アクセス
- Pydantic validation

### データと認証

- Supabase Auth
- Supabase Postgres
- Row Level Security
- Supabase 経由の Google OAuth

### 外部連携

- OpenAI
- Google Calendar
- Google Sheets
- Google Maps

---

## アーキテクチャ

```text
ShiftPilotAI/
├─ frontend/     Next.js アプリ、UI、API route proxy、Supabase セッション処理
├─ backend/      FastAPI、OpenAI オーケストレーション、Google / app tool 実行
├─ supabase/     DB migration と RLS policy
└─ docs/         設計メモ、意思決定、要件、作業ログ
```

### リクエストの流れ

```text
Browser
  ↓
Next.js frontend
  ↓
Next.js API routes
  ↓
FastAPI backend
  ↓
OpenAI / Google APIs / Supabase REST
```

フロントエンドは UI とログインセッションの扱いを担当します。バックエンドは AI 応答生成、意図分類、ツール実行、予定抽出、Google Maps 経路計算を担当します。

Supabase のデータアクセスは RLS でユーザーごとに分離しています。バックエンドから Supabase REST を呼ぶときも service role key ではなく、ログイン中ユーザーの JWT を使います。

---

## セキュリティメモ

このリポジトリでは、次のガードを入れています。

- 高コストな import / route planning API はログイン必須。
- backend の Google / import / mobility / app-data 系 API は Bearer 認証必須。
- Google provider token は HTTP-only Cookie に保存。
- 共有の `GOOGLE_REFRESH_TOKEN` fallback は使わない。
- 画像、チャットメッセージ、Google 操作、抽出候補などに payload 上限を設定。
- `APP_ENV=production` のとき FastAPI の docs/redoc を無効化。
- Supabase RLS で profile、event、location、calendar connection、import job、chat thread、chat message を所有ユーザーに限定。
- `npm audit --omit=dev` は現時点で脆弱性 0。

本番運用でさらに入れたいもの:

- API gateway や edge での rate limit。
- FastAPI backend を可能なら private network に閉じる。
- Google 書き込み/削除操作の監査ログ。
- CI での `pip-audit`。
- Google OAuth redirect URI の厳密な制限。

---

## ローカル開発

### 前提

- Next.js 16 に対応した Node.js
- Python 3.12+
- Supabase プロジェクト
- Google Cloud OAuth client
- Google Calendar API
- Google Sheets API
- Google Maps API
- OpenAI API key

### 1. フロントエンド依存関係をインストール

```bash
cd frontend
npm install
```

### 2. バックエンド依存関係をインストール

```bash
cd backend
python -m pip install -e .
```

### 3. 環境変数を設定

ローカル開発では `frontend/.env.local` にフロントエンドと backend から参照する値を置けます。

```bash
# Frontend / Supabase
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=

# Next.js API routes が呼ぶ backend URL
BACKEND_API_BASE_URL=http://127.0.0.1:8000

# OpenAI
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-nano
OPENAI_IMPORT_MODEL=gpt-5-nano

# Google OAuth / APIs
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:3000/auth/callback
GOOGLE_CALENDAR_ID=primary
GOOGLE_MAPS_API_KEY=
```

backend を単体でデプロイする場合は `backend/.env` に backend 関連の値を設定します。

```bash
APP_ENV=development
FRONTEND_ORIGIN=http://localhost:3000
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-nano
OPENAI_IMPORT_MODEL=gpt-5-nano
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:3000/auth/callback
GOOGLE_CALENDAR_ID=primary
GOOGLE_MAPS_API_KEY=
```

共有の `GOOGLE_REFRESH_TOKEN` は設定しないでください。Google 操作はログイン済みユーザーの provider token を使う前提です。

### 4. Supabase migration を適用

DB スキーマと RLS policy は `supabase/migrations/` にあります。

Supabase CLI を使う場合:

```bash
supabase db push
```

主なテーブル:

- profiles
- saved_locations
- calendar_connections
- import_jobs
- events
- event_travel_plans
- chat_threads
- chat_messages

### 5. バックエンドを起動

```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

ヘルスチェック:

```text
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8000/api/health
```

### 6. フロントエンドを起動

```bash
cd frontend
npm run dev
```

ブラウザで開く:

```text
http://localhost:3000
```

---

## よく使うコマンド

### フロントエンド

```bash
cd frontend
npm run dev
npm run lint
npm run build
npm audit --omit=dev
```

### バックエンド

```bash
cd backend
python -m compileall app
python -m uvicorn app.main:app --reload --port 8000
```

---

## 主なルート

### フロントエンドページ

- `/` - 公開ランディングページ
- `/login` - Google ログイン
- `/calendar` - 月カレンダー
- `/timeline` - 日別タイムライン
- `/chat` - AI スケジューリングチャット
- `/settings` - 言語、同期、移動、外部連携設定

### Next.js API Routes

- `/api/chat`
- `/api/chat/threads`
- `/api/import/preview`
- `/api/import/commit`
- `/api/mobility/plan`
- `/api/mobility/schedule`
- `/api/sync/google-calendar`
- `/api/settings/*`

### FastAPI Routes

- `/health`
- `/api/health`
- `/api/chat/stream`
- `/api/import/preview`
- `/api/mobility/plan`
- `/api/google/calendar/list`
- `/api/google/calendar/create`
- `/api/google/calendar/delete`
- `/api/google/calendar/delete-range`
- `/api/google/sheets/preview`
- `/api/app/events/search`
- `/api/app/home-context`
- `/api/app/chat/threads/{thread_id}`
- `/api/app/chat/messages/replace`

多くの backend API は Bearer token が必要です。

---

## 現在の制約

- 公共交通機関の経路検索は未実装。
- チーム共同編集や複数人シフト管理は対象外。
- 予定取り込みは LLM 抽出に依存するため、保存前の確認が必要。
- 本番運用では rate limit と監視を追加するのが望ましい。
- アプリ内カレンダーだけへの import 保存は一部段階的実装。現時点では Google Calendar 保存が主経路。

---

## Roadmap 案

- 公共交通機関の経路検索。
- 予定候補の一括編集 UI。
- 繰り返しシフトの扱いを強化。
- スマホでシフト表を撮ってすぐ取り込む導線。
- カレンダー競合解決アシスタント。
- Cookie 以外のユーザー別 Google token 保管戦略。
- Vercel、Fly.io、Render などへのデプロイガイド。
- API route security と import validation のテスト追加。

---

## GitHub Topics 案

```text
ai
scheduler
google-calendar
google-sheets
google-maps
shift-scheduling
travel-planning
nextjs
fastapi
supabase
openai
typescript
python
```

---

## ライセンス

現時点ではライセンス未設定です。外部配布やコントリビューション受付を行う場合は、先にライセンスを追加してください。

---

## 作者

Kaisei Yasuzaki
