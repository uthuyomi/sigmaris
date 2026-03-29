# 2026-03-28 Supabase Auth と Google OAuth の SSR 導線を入れる

## 日付
- 2026-03-28

## 決定
- 認証は `Supabase Auth + Google OAuth` で進める。
- Next.js 側は SSR クライアントと `proxy.ts` を使ってセッションを更新する。
- Google Sheets と Google Calendar のユーザー連携は、Google provider token を使う形で始める。

## 理由
- 初期構成としては Google 一本のほうが実装も検証も速い。
- Supabase Auth を使うとログイン状態の扱いをアプリ全体で揃えやすい。
- すでに Google の各種 API を使う前提なので、OAuth もその流れに揃えた方が自然。

## 実装メモ
- `/auth/callback` で code exchange を行う。
- Google provider token は Cookie に保持する。
- API route からは Cookie の token を優先して Google API を呼ぶ。

## 保留
- provider token を DB に保存するかどうか
- ログイン必須ページの範囲
- 複数 Google カレンダー選択 UI
