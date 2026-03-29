# Chat Thread Persistence

## 目的
- AI とユーザーのメッセージを DB に残す。
- 過去スレッドの再開、スレッド名変更、削除を可能にする。
- ChatGPT のようにスレッド一覧から会話を切り替えられる形にする。

## DB
- `chat_threads`
  - スレッド本体
  - `title`, `user_id`, `updated_at`
- `chat_messages`
  - スレッド配下のメッセージ
  - `thread_id`, `message_order`, `role`, `parts`, `metadata`

## 実装
- [chat/page.tsx](/d:/souce/ShiftPilotAI/src/app/chat/page.tsx)
  - スレッド一覧と会話本体の 2 カラム構成
- [assistant.tsx](/d:/souce/ShiftPilotAI/src/app/assistant.tsx)
  - `threadId` と `initialMessages` を受けて会話を開始
- [chat-thread-sidebar.tsx](/d:/souce/ShiftPilotAI/src/components/chat-thread-sidebar.tsx)
  - 新規作成、名前変更、削除
- [chat-threads.ts](/d:/souce/ShiftPilotAI/src/lib/chat-threads.ts)
  - スレッド CRUD とメッセージ保存
- [route.ts](/d:/souce/ShiftPilotAI/src/app/api/chat/route.ts)
  - 応答完了時にスレッドの全メッセージを保存

## 注意点
- 画像添付の生データは DB 肥大化を避けるため保存時に落としている。
- スレッドタイトルは初回メッセージから自動で付くが、あとで変更できる。
- 利用前に Supabase migration を流す必要がある。
