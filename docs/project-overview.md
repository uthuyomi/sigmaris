# Project Overview

## 目的

シグマリス は、チャットを入口にして予定を組み、カレンダー・タイムライン・Google 連携まで一気通貫で扱える予定調整アプリだよ。  
単なるカレンダー入力ではなく、次の流れを主軸にしている。

1. チャットで相談する
2. 画像や Google Sheets から予定候補を取り込む
3. カレンダーとタイムラインで確認する
4. Google Calendar に反映する
5. 必要なら移動時間や交通手段まで考慮する

## 現在の技術構成

### フロントエンド

- `frontend/`
- `Next.js`
- `TypeScript`
- `Tailwind CSS`
- `assistant-ui`
- `@ai-sdk/react`

### バックエンド

- `backend/`
- `FastAPI`
- `Python`
- `OpenAI Responses API`

### データ・認証

- `Supabase`
- `Supabase Auth`
- `Google OAuth`

### 外部連携

- `Google Calendar`
- `Google Sheets`
- `Google Maps`

## プロダクトの主な機能

### 予定管理

- 月表示カレンダー
- 日付を起点にしたタイムライン表示
- 24時間ベースの予定管理
- 5 / 10 / 15 / 30 / 60 分粒度

### チャット

- スレッド単位の会話保存
- スレッド名変更
- スレッド削除
- 過去会話の再開
- AI 口調の切り替え

### 取り込み

- 画像添付から勤務表や予定候補を抽出
- Google Sheets URL から予定候補を抽出
- 抽出結果を確認して Google Calendar へ登録

### Google 連携

- Google Calendar の読み取り
- Google Calendar への追加
- Google Calendar の削除・範囲削除
- Google Sheets のプレビュー取得

### 移動計画

- 自宅 / 保存地点 / 手入力地点を出発地にできる
- 電車 / バス / 自転車 / 自家用車 / 徒歩に対応
- 予定開始時刻に間に合う出発時刻を逆算
- 公共交通候補を前倒しで複数探索

### 設定

- 言語切り替え
- AI 口調切り替え
- Google カレンダー同期 ON/OFF
- 保存地点管理
- 既定の移動手段設定

## 現在の責務分離

### frontend が担うもの

- 画面表示
- ユーザー操作
- Supabase セッション取得
- backend API への proxy

### backend が担うもの

- chat request の意図分類
- OpenAI への最終問い合わせ
- Google API 実行
- import 解析
- mobility 計算
- app event 検索
- chat message 保存

## 現在の backend chat の考え方

chat は backend で次の順番で動く。

1. ユーザー入力と添付を受ける
2. request intent を分類する
3. intent ごとに使うツールを絞る
4. 必要な Google / app data ツールを実行する
5. 最終的な返答を LLM で生成する
6. chat thread に保存する

## 現在のディレクトリ構成

- `frontend/`: UI と proxy
- `backend/`: API と業務ロジック
- `supabase/`: migration
- `docs/`: 設計・判断・運用記録

## Notion へ移す時の親ページ候補

- プロジェクト概要
- Notion 配置図
- 要件
- 設計
- backend 設計
- Google 連携
- chat / AI
- データモデル
- 判断記録
- 作業ログ
