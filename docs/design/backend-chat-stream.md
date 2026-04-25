# Backend Chat Stream

## 目的

chat の最終生成を frontend ではなく backend に寄せて、AI 実行の中枢を Python 側に集めることが目的だよ。

## 現在の流れ

1. frontend で user message を送る
2. frontend `/api/chat` が raw body を backend `/api/chat/stream` に転送する
3. backend が Supabase JWT と Google token を受ける
4. backend が request を分類する
5. backend が必要な tool を選ぶ
6. backend が OpenAI Responses API を実行する
7. backend が assistant message を保存する
8. backend が AI SDK 互換 SSE を返す

## frontend の役割

- UI を持つ
- session を取る
- Supabase JWT を付ける
- Google provider token を付ける
- backend の stream をそのまま返す

## backend の役割

- system prompt の構築
- AI tone の反映
- 画像添付の要約反映
- request intent の分類
- tool の選択
- Google / app data / mobility / import の実処理
- assistant message 保存
- SSE 生成

## request routing

backend では、いきなり最終 LLM に投げるのではなく、先に request routing を通している。

### routing の段階

1. heuristic でざっくり判定
2. 曖昧なら LLM で fallback 分類
3. intent ごとに使う tool を制限
4. 最終 LLM へ渡す

### intent の種類

- `general_chat`
- `event_lookup`
- `mobility_plan`
- `schedule_import`
- `calendar_write`
- `sync_control`

## この構成にした理由

- 毎回フル tool を使わせると精度がぶれやすい
- chat / import / mobility / calendar write は性質がかなり違う
- Python 側で request を振り分けた方が責務もテストも整理しやすい

## 現状の注意点

- stream は AI SDK 互換 SSE で返している
- 途中 token をそのまま逐次転送するより、backend 側で最終結果をまとめて流す現在の形を優先している
- さらに細かいリアルタイム可視化は今後の改善対象
