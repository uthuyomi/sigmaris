# Requirements

ここには、ユーザー体験として何を実現したいかをまとめる。

## 中核要件

- チャットを主導線にする
- 時間帯ベースで予定を管理する
- 画像や Google Sheets から予定候補を取り込める
- Google Calendar と双方向でやり取りできる
- 自宅や移動手段を考慮した移動計画ができる

## 主要ページ

- [time-based-scheduling.md](/d:/souce/ShiftPilotAI/docs/requirements/time-based-scheduling.md)
- [product-scope.md](/d:/souce/ShiftPilotAI/docs/requirements/product-scope.md)

## 要件メモ

- 単純な月間カレンダーだけではなく、24時間ベースの扱いが必要
- 5分単位まで調整できる柔軟性が必要
- AI が既存予定や自宅情報を参照して会話を補完できることが望ましい
- Google 連携は login から calendar / sheets / maps まで一貫して扱える構成が必要
