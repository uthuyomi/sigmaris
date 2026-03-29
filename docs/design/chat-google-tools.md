# Chat Google Tools

## 目的
- チャットの中で Google 系サービスを行き来しながら予定調整を進める。

## 現在チャットから使えるもの
- Google Calendar の予定取得
- Google Calendar の予定登録
- Google Sheets の先頭シート読み取り
- Google Maps の経路計算

## 実装
- `src/app/api/chat/route.ts`
  - `list_google_calendar_events`
  - `create_google_calendar_events`
  - `read_google_sheet`
  - `plan_google_route`

## ねらい
- AI が既存予定を見てから提案する
- シートの内容を確認して予定候補へつなぐ
- 移動時間を見て間に合う時間へ補正する
- ユーザー確認後にカレンダーへ登録する

## 注意点
- 画像添付からの予定抽出はまだチャット内で完全自動接続されていない
- 現在は画像解析 API とカレンダー登録 API が別にある
