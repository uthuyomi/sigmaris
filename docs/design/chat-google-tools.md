# Chat Google Tools

## 目的
- チャットの中で Google 連携を完結させ、予定確認から削除、再登録まで進められるようにする。

## 現在チャットから使えるもの
- Google Calendar の予定取得
- Google Calendar の予定追加
- Google Calendar の予定削除
- Google Calendar の期間指定削除
- Google Sheets の URL 読み取り
- Google Maps の経路計算

## 実装
- [route.ts](/d:/souce/ShiftPilotAI/src/app/api/chat/route.ts)
  - `list_google_calendar_events`
  - `create_google_calendar_events`
  - `delete_google_calendar_events`
  - `delete_google_calendar_events_in_range`
  - `read_google_sheet`
  - `plan_google_route`
- [calendar.ts](/d:/souce/ShiftPilotAI/src/lib/google/calendar.ts)

## 運用ルール
- 追加前は登録内容を要約して確認する。
- 削除前は削除件数、対象期間、対象タイトルを要約して確認する。
- 月単位の入れ替えは `一覧取得 -> 範囲削除 -> 再登録` の順で進める。
- 添付画像の抽出結果は参考情報として扱い、ユーザー本文を優先する。
