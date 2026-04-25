# 2026-03-31 Comprehensive Log

## 目的

このページは、会話で決まった内容と実装済みの構成を突き合わせて、後から全体を追えるようにするための補完ログだよ。

## ここまでの大きな流れ

### 1. 初期方針の確定

- Next.js + TypeScript を土台にする
- Supabase を保存基盤にする
- 認証は最終的に Google OAuth 中心に寄せる
- UI はワイヤーフレームなしで先に作る
- 予定は日付埋めではなく時間帯ベースで扱う

### 2. 予定管理 UI の整備

- calendar と timeline を分けた
- 月表示から日付選択で timeline に降りる形にした
- 時間粒度は 5 / 10 / 15 / 30 / 60 分で扱える方針にした

### 3. chat 主導線の整備

- assistant-ui ベースの chat UI を入れた
- thread persistence を入れた
- chat thread の一覧、名称変更、削除を入れた
- AI tone の切り替えを入れた

### 4. Google 連携

- Google Calendar 読み取り
- Google Calendar 追加
- Google Calendar 削除、範囲削除
- Google Sheets preview
- Google Maps mobility

### 5. import

- 画像から予定候補抽出
- Google Sheets から予定候補抽出
- chat を入口にしてカレンダー登録まで進める流れを作った

### 6. mobility

- 自宅 / 保存地点 / 手入力地点を起点にできる
- 電車 / バス / 自転車 / 自家用車 / 徒歩に対応
- 予定開始時刻に間に合う時刻を逆算する
- transit 候補を複数探索する

### 7. frontend / backend 分離

- `frontend/` に Next.js を集約
- `backend/` に FastAPI を追加
- mobility, import, Google tools, app-data, chat を順次 backend へ移した

### 8. backend chat stream

- backend 側に chat stream endpoint を作成
- frontend `/api/chat` は proxy のみにした
- Supabase JWT と Google provider token を backend に引き渡す形にした

### 9. intent routing

- backend で入力分類を入れた
- まず heuristic で分類
- 曖昧なら LLM で fallback 分類
- intent ごとに tool を絞って最終 LLM に渡す形にした

## 現在の主な backend 機能

- chat stream
- app event search
- home context
- Google Calendar / Sheets
- mobility
- import preview

## 現在の主な frontend 機能

- public top / login / app shell
- chat / calendar / settings
- icon-first なナビゲーション
- language / AI tone / travel mode / saved locations 設定

## 補足

既存 docs には途中段階のメモも残っている。  
このページは、それらを横断して「今どうなっているか」を追いやすくするための補完ログとして使う想定だよ。
