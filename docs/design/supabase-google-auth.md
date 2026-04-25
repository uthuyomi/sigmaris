# Supabase Google Auth

## 目的
- 初期認証を Google OAuth 一本に絞り、ログイン導線を単純に保つ。
- Supabase Auth を使ってセッション管理をまとめる。
- Google Calendar と Google Sheets をユーザーごとの Google アカウントで扱える土台を作る。

## 現在の実装
- `src/lib/supabase/client.ts`
  - Client Component 用の Supabase クライアント。
- `src/lib/supabase/server.ts`
  - Route Handler と Server Component 用の Supabase クライアント。
- `src/lib/supabase/proxy.ts`
  - 認証セッション更新用の処理。
- `proxy.ts`
  - 全体のセッション更新導線。
- `src/app/auth/callback/route.ts`
  - OAuth コードをセッションへ交換する。
- `src/app/auth/signout/route.ts`
  - ログアウトと Google provider cookie の削除を行う。
- `src/components/auth-controls.tsx`
  - Google ログイン、ログアウト、現在のログイン状態表示。

## Google provider token の扱い
- `src/lib/google/provider-tokens.ts` で provider token と refresh token を Cookie に保存する。
- Google Sheets と Google Calendar のヘルパーは、まずこの Cookie の token を使う。
- token がない場合はエラーにする。共有の `GOOGLE_REFRESH_TOKEN` fallback は使わない。

## 必要な外部設定
- Supabase プロジェクト
- Supabase の Google Provider 有効化
- Google Cloud OAuth クライアント
- Redirect URL の登録
- ユーザーごとの Google provider token

## 次の候補
- ユーザープロフィールを Supabase DB 側へ保存
- ログイン必須ページの保護
- provider token の保存先を Cookie から DB へ切り替えるか検討
