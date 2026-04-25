# Backend Endpoint Catalog

## 目的

このページは、`backend/` にある API 群を一覧化して、frontend から何をどこに渡しているか、どの責務がどの endpoint に乗っているかを追いやすくするためのものだよ。  
会話の中で段階的に backend へ寄せていった経緯があるので、最終的な置き場所を明文化しておくのがミソだね。

## 共通前提

- backend は `FastAPI`
- frontend は `Next.js`
- frontend は必要に応じて proxy route を持つ
- backend は `Supabase JWT` と `Google provider token` を受け取って業務処理を行う

## Health

### `/health`

- 用途: backend の基本疎通確認
- 主な利用箇所: frontend 設定画面の backend 状態表示

### `/api/health`

- 用途: API 名前空間配下の疎通確認
- 主な利用箇所: frontend 側 proxy や backend client のヘルス確認

## Chat

### `/api/chat/capabilities`

- 用途: backend chat が持つ能力や構成の確認
- 補足: backend へ chat stream を移した後の状態確認にも使う

### `/api/chat/stream`

- 用途: chat request を受けて、intent 分類、tool 実行、最終 LLM 応答、thread 保存まで行う
- 主な処理:
  - request intent 分類
  - app data 検索
  - Google tools 実行
  - import / mobility 系補助呼び出し
  - assistant message 保存
- frontend 側: `frontend/src/app/api/chat/route.ts` が proxy する

## Google Tools

### `/api/google/calendar/list`

- 用途: Google Calendar の event 一覧取得
- 主な利用: chat 内の既存予定確認、同期処理

### `/api/google/calendar/create`

- 用途: Google Calendar への event 追加
- 主な利用: import 後の登録、chat からの予定反映

### `/api/google/calendar/delete`

- 用途: event ID 指定で個別削除
- 主な利用: chat からの置換登録前削除

### `/api/google/calendar/delete-range`

- 用途: 期間と条件指定でまとめて削除
- 主な利用: 月単位の勤務入れ替えや再登録

### `/api/google/sheets/preview`

- 用途: Google Sheets の URL / spreadsheet 情報から preview を返す
- 主な利用: import の前段確認

## Mobility

### `/api/mobility/plan`

- 用途: 起点、終点、交通手段、到着希望時刻から route plan を返す
- 主な利用: timeline 側 mobility panel、chat 内移動相談

### `/api/mobility/transit-candidates`

- 用途: 公共交通の到着候補を前倒ししながら複数探索する
- 主な利用: chat から「早すぎず間に合う便」を探す処理

## Import

### `/api/import/preview`

- 用途: 画像または sheet 内容から予定候補を抽出し、preview を返す
- 主な利用: chat 添付、import preview route

## App Data

### `/api/app/events/search`

- 用途: 自前 DB の予定検索
- 主な利用: `円山センターの日` みたいな自然言語参照の補完

### `/api/app/home-context`

- 用途: 自宅住所、保存地点、既定移動手段などのプロフィール文脈を返す
- 主な利用: chat の移動相談補完

### `/api/app/chat/threads/{thread_id}`

- 用途: thread 存在確認と thread 情報取得
- 主な利用: chat stream 実行前の thread 文脈確認

### `/api/app/chat/messages/replace`

- 用途: thread message をまとめて置換保存
- 主な利用: backend chat stream 完了後の message 永続化

## frontend 側 proxy の考え方

frontend には route が残っていても、役割は次のどちらかに寄せている。

- backend への単純 proxy
- frontend セッションや cookie から token を拾って backend に橋渡しする

つまり、業務ロジックそのものは backend に置き、frontend route は transport の薄い層に寄せる方針だよ。

## 今後の見方

Notion に移す時は、このページを backend 親ページの先頭に置いておくといい。  
新しい endpoint を増やした時も、ここに追記していけば「何がどこにあるか」が崩れにくいってわけさ。
