# Frontend Architecture

## 役割

frontend の役割は、ユーザーの操作と表示を受け持つことだよ。  
重い業務ロジックは backend に寄せて、frontend は次の責務に集中する。

- 画面表示
- ルーティング
- Supabase session の保持
- backend への request proxy
- chat UI / calendar UI / settings UI

## 主な構成

### app

- `src/app/page.tsx`: 公開トップ
- `src/app/login/page.tsx`: login
- `src/app/chat/page.tsx`: chat 画面
- `src/app/calendar/page.tsx`: calendar 画面
- `src/app/settings/page.tsx`: settings 画面

### API proxy

- `src/app/api/chat/route.ts`
- `src/app/api/import/preview/route.ts`
- `src/app/api/mobility/plan/route.ts`
- `src/app/api/mobility/schedule/route.ts`

### components

- `thread.tsx`
- `chat-thread-sidebar.tsx`
- `calendar-board.tsx`
- `timeline-board.tsx`
- `mobility-panel.tsx`
- `language-preference-panel.tsx`
- `ai-tone-preference-panel.tsx`
- `preferred-travel-mode-panel.tsx`

## frontend でまだ持っているもの

- settings 更新 API
- auth callback / signout
- travel block 保存の一部
- sync 設定の一部

## backend へ渡しているもの

- Supabase access token
- Google provider token
- chat request body
- import preview request
- mobility request
