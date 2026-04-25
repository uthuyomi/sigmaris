# 2026-03-31 Backend Refactor And Intent Routing

## 決定内容

frontend で抱えていた chat / import / mobility / Google API 実行を、できるだけ backend に寄せる方針を採用した。  
さらに chat については、backend 側で入力を意図分類してから最終 LLM に渡す構成にした。

## 理由

- frontend に重い処理が集まりすぎると不安定になりやすい
- Google API と OpenAI を backend に寄せた方が責務が明確になる
- chat の精度を上げるには、毎回フル装備で処理するより request routing が必要
- 後で worker 化や retry を入れる時も backend 起点の方が拡張しやすい

## 採用した構成

### frontend

- UI
- session 取得
- backend proxy

### backend

- chat stream
- intent routing
- Google Calendar / Sheets
- mobility
- import preview
- app event search
- chat message persistence

## chat routing の方針

以下の intent を backend で分類する。

- `general_chat`
- `event_lookup`
- `mobility_plan`
- `schedule_import`
- `calendar_write`
- `sync_control`

分類後は、その intent に必要な tool だけを最終 LLM に渡す。

## 影響

- frontend の `/api/chat` は薄い proxy になった
- backend の chat service が中枢になった
- docs も frontend/backend 前提で読み直せるように補完した
