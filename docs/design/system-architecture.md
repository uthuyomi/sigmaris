# System Architecture

## 全体像

現在の シグマリス は、`frontend` と `backend` を分けた二層構成になっている。

- `frontend`
  - Next.js
  - UI
  - session 取得
  - backend proxy
- `backend`
  - FastAPI
  - OpenAI orchestration
  - Google API 実行
  - mobility / import / chat routing
- `Supabase`
  - Auth
  - DB
  - RLS

## データの流れ

### chat

1. ユーザーが frontend でメッセージ送信
2. frontend `/api/chat` が Supabase JWT と Google token を付けて backend に転送
3. backend が request intent を分類
4. 必要な tool だけ使って OpenAI Responses API を実行
5. backend が chat thread を保存
6. backend が SSE を返し、frontend が UI に反映

### import

1. ユーザーが画像または Google Sheets URL を渡す
2. frontend が backend import endpoint を叩く
3. backend が画像/表データから予定候補を抽出する
4. chat または UI で確認する

### mobility

1. 出発地と目的地を決める
2. backend が Geocoding / Places / Directions 相当の処理を進める
3. 交通手段ごとに候補を返す
4. 必要なら travel block として保存する

## なぜ分けたか

- frontend に重い API 処理を持たせすぎると不安定になりやすい
- chat / import / mobility は retry や routing を backend で持った方が素直
- Google API と OpenAI を backend に寄せた方が責務が明確になる
