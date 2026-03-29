# プロジェクト概要

## 目的
- チャットで予定を組み、カレンダーとタイムラインで調整し、外部サービスへ反映できる Web アプリを作る。
- 予定だけでなく、移動時間や外部データ取り込みも一連の流れとして扱う。

## 現在の方針
- アプリ基盤: `Next.js`
- 言語: `TypeScript`
- ユーザーデータ保存: `Supabase`
- 認証: `Supabase Auth + Google OAuth`
- AI 連携: `OpenAI`
- 外部連携: `Google Sheets` `Google Calendar` `Google Maps`

## 体験の中心
- チャットで予定を相談する。
- カレンダーで日付を決める。
- タイムラインで細かい時間を詰める。
- 場所付き予定には移動計画を重ねる。

## 実装済みの主な要素
- ホーム、チャット、カレンダー、タイムライン、設定の各画面
- Google Sheets URL と画像ファイルからの予定候補取り込み
- Google Calendar への予定反映
- Google Maps を使った移動時間の試算

## 次にやること
- Google OAuth のユーザー単位接続
- Supabase Auth の本接続
- Places API を使った場所補完
- チャット内だけで登録まで完了する流れの強化
