# Backend API Architecture

## 目的

backend は、frontend から切り離して重い業務処理を担当する層として置いている。  
役割をはっきり分けることで、UI 側は軽く保ちつつ、AI や Google API の処理を安定させるのが狙いだよ。

## backend の責務

### chat

- request intent の分類
- OpenAI Responses API の実行
- tool 実行の制御
- assistant message の生成
- chat thread 保存

### google tools

- Google Calendar の読み取り
- Google Calendar への追加
- Google Calendar の削除
- Google Sheets の preview 取得

### mobility

- Geocoding
- route lookup
- transit candidate search

### import

- 画像からの予定候補抽出
- sheet row からの予定候補抽出

### app data

- event search
- home context lookup
- thread existence 確認
- message replace

## 主なファイル

- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/routes/chat.py`
- `backend/app/routes/google_tools.py`
- `backend/app/routes/mobility.py`
- `backend/app/routes/import_preview.py`
- `backend/app/routes/app_data.py`
- `backend/app/services/chat.py`
- `backend/app/services/chat_routing.py`
- `backend/app/services/google_api.py`
- `backend/app/services/google_calendar.py`
- `backend/app/services/google_sheets.py`
- `backend/app/services/google_maps.py`
- `backend/app/services/import_extract.py`
- `backend/app/services/app_data.py`
- `backend/app/services/supabase_rest.py`

## 認証と token の流れ

### Supabase

- frontend が Supabase session を持つ
- frontend が `Authorization: Bearer <supabase access token>` を backend に渡す
- backend は PostgREST + RLS 経由で app data を読む

### Google

- frontend が provider token を cookie 経由で保持する
- frontend が backend へ Google token を custom header で渡す
- backend が Google Calendar / Sheets API を実行する

## endpoint 構成

### chat

- `/api/chat/capabilities`
- `/api/chat/stream`

### google

- `/api/google/calendar/list`
- `/api/google/calendar/create`
- `/api/google/calendar/delete`
- `/api/google/calendar/delete-range`
- `/api/google/sheets/preview`

### mobility

- `/api/mobility/plan`
- `/api/mobility/transit-candidates`

### import

- `/api/import/preview`

### app data

- `/api/app/events/search`
- `/api/app/home-context`
- `/api/app/chat/threads/{thread_id}`
- `/api/app/chat/messages/replace`

## 補足

frontend は backend を直接使うのではなく、必要に応じて Next.js route を経由して proxy する。  
この形にしておくと、UI 側のコードを大きく変えずに backend の責務を広げやすい。
