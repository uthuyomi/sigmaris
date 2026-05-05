# UI Map

ShiftPilotAI frontend の UI 配線図です。画面ルート、主要コンポーネント、i18n/コピー、UIから呼ばれる API を追うための保守メモです。

## App Entry

| UI | File | Connects To | Notes |
| --- | --- | --- | --- |
| Root layout | `frontend/src/app/layout.tsx` | `TooltipProvider` from `components/ui`, `globals.css` | 全ページ共通レイアウト、フォント、metadata |
| Global style | `frontend/src/app/globals.css` | Tailwind/global CSS | 全 UI のベーススタイル |
| Web manifest | `frontend/src/app/manifest.ts` | PWA metadata | PWA の表示名、icon 設定 |
| Launch redirect | `frontend/src/app/launch/page.tsx` | `getCurrentUser` | ログイン状態に応じて `/app` or `/login` へ誘導 |

## Pages

| Page | Route | File | Main Components | i18n / Copy | Data / API |
| --- | --- | --- | --- | --- | --- |
| Landing | `/` | `frontend/src/app/page.tsx` | `LandingPageContent` | `frontend/src/i18n/landing/*` | `getCurrentUser`, `headers` |
| Login | `/login` | `frontend/src/app/login/page.tsx` | `AuthControls` | `frontend/src/i18n/login/*`, `defaultLocale` | `getCurrentUser` |
| App home | `/app` | `frontend/src/app/app/page.tsx` | redirects / overview entry | shared i18n when routed onward | auth/profile routing |
| Chat | `/chat` | `frontend/src/app/chat/page.tsx` | `AppShell`, `ChatWorkspace`, `Assistant`, `Thread`, `ChatThreadSidebar` | `getDictionary(locale)` | `requireUser`, chat thread libs, `/api/chat`, `/api/chat/threads` |
| Calendar | `/calendar` | `frontend/src/app/calendar/page.tsx` | `AppShell`, `CalendarBoard`, `CalendarLiveSync` | `getDictionary(locale)` | `listEventsForMonthForUser`, `/api/sync/google-calendar` |
| Timeline | `/timeline` | `frontend/src/app/timeline/page.tsx` | `AppShell`, `TimelineBoard` | `getDictionary(locale)` | `listEventsForDateForUser`, mobility APIs via side panel |
| Settings | `/settings` | `frontend/src/app/settings/page.tsx` | `AppShell`, settings panels | `getDictionary(locale)` | profile settings, integration capability checks |

## Loading UI

| Route | File | Component |
| --- | --- | --- |
| `/chat` | `frontend/src/app/chat/loading.tsx` | `RouteLoadingSkeleton` |
| `/calendar` | `frontend/src/app/calendar/loading.tsx` | `RouteLoadingSkeleton` |
| `/timeline` | `frontend/src/app/timeline/loading.tsx` | `RouteLoadingSkeleton` |
| `/settings` | `frontend/src/app/settings/loading.tsx` | `RouteLoadingSkeleton` |

## Shared App Shell

| Component | File | Used By | Connects To |
| --- | --- | --- | --- |
| `AppShell` | `frontend/src/components/app-shell.tsx` | Chat, Calendar, Timeline, Settings | `AuthControls`, `Tooltip`, `getDictionary`, route navigation |
| `AuthControls` | `frontend/src/components/auth-controls.tsx` | `AppShell`, Login | Supabase client, Google OAuth, auth i18n |
| `RouteLoadingSkeleton` | `frontend/src/components/route-loading-skeleton.tsx` | loading routes | Shared loading shell |
| `TooltipIconButton` | `frontend/src/components/tooltip-icon-button.tsx` | Markdown/code actions | `Button` |

## Landing UI

| Component / Data | File | Used By | Purpose |
| --- | --- | --- | --- |
| `LandingPageContent` | `frontend/src/components/landing/landing-page-content.tsx` | `/` | Landing の見た目全体 |
| Landing barrel | `frontend/src/components/landing/index.ts` | `/` | `LandingPageContent` export |
| Landing copy | `frontend/src/i18n/landing/copies.ts` | `/` | Landing の locale 別コピー |
| Landing locale resolver | `frontend/src/i18n/landing/locale.ts` | `/` | `Accept-Language` から `AppLocale` を決定 |
| Landing types | `frontend/src/i18n/landing/types.ts` | Landing copy/content | `LandingCopy`, `LandingUseCaseIcon` |

## Login UI

| Component / Data | File | Used By | Purpose |
| --- | --- | --- | --- |
| Login page | `frontend/src/app/login/page.tsx` | `/login` | Login 画面本体 |
| Login copy | `frontend/src/i18n/login/copy.ts` | Login page | ログイン画面文言、連携ツール一覧 |
| Login types | `frontend/src/i18n/login/types.ts` | Login copy/page | `LoginToolIcon`, `LoginToolCopy` |
| Login barrel | `frontend/src/i18n/login/index.ts` | Login page | login i18n exports |

## Chat UI

| Component / Data | File | Used By | Purpose |
| --- | --- | --- | --- |
| `Assistant` | `frontend/src/app/assistant.tsx` | Chat page | assistant-ui runtime と `/api/chat` transport |
| `ChatWorkspace` | `frontend/src/components/chat-workspace.tsx` | Chat page | Chat layout, sidebar + thread |
| `ChatThreadSidebar` | `frontend/src/components/chat-thread-sidebar.tsx` | `ChatWorkspace` | thread list, rename/delete/new |
| `Thread` | `frontend/src/components/thread.tsx` | `Assistant` | Message list, composer, prompt template selector |
| Prompt templates | `frontend/src/components/thread-prompt-templates.ts` | `Thread` | Composer に挿入する定型プロンプト |
| `Attachment` components | `frontend/src/components/attachment.tsx` | `Thread` | Composer/user message attachments |
| `MarkdownText` | `frontend/src/components/markdown-text.tsx` | `Thread` | Assistant message markdown rendering |
| `ToolFallback` | `frontend/src/components/tool-fallback.tsx` | assistant-ui tool rendering | Tool call fallback UI |
| `ImportEntryPanel` | `frontend/src/components/import-entry-panel.tsx` | Chat/import flows | Sheets/image import preview + commit UI |

## Calendar UI

| Component | File | Used By | Purpose |
| --- | --- | --- | --- |
| `CalendarBoard` | `frontend/src/components/calendar-board.tsx` | Calendar page | Month grid and day links |
| `CalendarLiveSync` | `frontend/src/components/calendar-live-sync.tsx` | Calendar page | Google Calendar sync trigger/timer |
| Calendar page data | `frontend/src/app/calendar/page.tsx` | Calendar route | month parsing, event fetch, shell settings |

## Timeline And Mobility UI

| Component / Module | File | Used By | Purpose |
| --- | --- | --- | --- |
| `TimelineBoard` | `frontend/src/components/timeline-board.tsx` | Timeline page | Day timeline container and grain control |
| `TimelineDayGrid` | `frontend/src/components/timeline/timeline-day-grid.tsx` | `TimelineBoard` | Time grid |
| `TimelineEventCard` | `frontend/src/components/timeline/timeline-event-card.tsx` | `TimelineDayGrid` | Event card rendering |
| `TimelineSidePanel` | `frontend/src/components/timeline/timeline-side-panel.tsx` | `TimelineBoard` | Selected event details + mobility panel |
| Timeline barrel | `frontend/src/components/timeline/index.ts` | `TimelineBoard` | timeline component exports |
| `MobilityPanel` | `frontend/src/components/mobility-panel.tsx` | `TimelineSidePanel` | Travel plan input and preview |
| Mobility sections | `frontend/src/components/mobility/panel-sections.tsx` | `MobilityPanel` | Origin controls, travel mode, preview cards |
| Mobility API helpers | `frontend/src/components/mobility/api.ts` | `MobilityPanel`, mobility sections | Browser API and `/api/mobility/*` helper calls |
| Mobility types | `frontend/src/components/mobility/types.ts` | Mobility modules | Travel UI response/input types |
| Mobility barrel | `frontend/src/components/mobility/index.ts` | `MobilityPanel` | mobility exports |

## Settings UI

| Component | File | Used By | API / Data |
| --- | --- | --- | --- |
| Settings page | `frontend/src/app/settings/page.tsx` | `/settings` | `readSettingsPageSettings`, integration config checks |
| Settings barrel | `frontend/src/components/settings/index.ts` | Settings page | settings panel exports |
| `ThemePreferencePanel` | `frontend/src/components/theme-preference-panel.tsx` | Settings page | `/api/settings/theme` |
| `LanguagePreferencePanel` | `frontend/src/components/language-preference-panel.tsx` | Settings page | `/api/settings/language`, supported locales |
| `AiTonePreferencePanel` | `frontend/src/components/ai-tone-preference-panel.tsx` | Settings page | `/api/settings/ai-tone` |
| `PreferredTravelModePanel` | `frontend/src/components/preferred-travel-mode-panel.tsx` | Settings page | `/api/settings/travel-mode` |
| `ArrivalLeadMinutesPanel` | `frontend/src/components/arrival-lead-minutes-panel.tsx` | Settings page | `/api/settings/arrival-lead-minutes` |
| `GoogleCalendarSyncPanel` | `frontend/src/components/google-calendar-sync-panel.tsx` | Settings page | `/api/settings/google-calendar-sync`, `/api/sync/google-calendar` |
| `SavedLocationsPanel` | `frontend/src/components/saved-locations-panel.tsx` | Settings page | `/api/settings/locations`, `/api/settings/locations/[locationId]` |
| `IntegrationStatusPanel` | `frontend/src/components/integration-status-panel.tsx` | Settings page | `/api/backend/health`, `/api/backend/chat-capabilities` |

## Overview UI

| Component / Data | File | Used By | Purpose |
| --- | --- | --- | --- |
| `OverviewDashboard` | `frontend/src/components/overview-dashboard.tsx` | App home / overview surface | Workflow cards and status overview |
| Overview data | `frontend/src/components/overview-dashboard-data.ts` | `OverviewDashboard` | Card labels and status text |

## UI Primitives

| Primitive | File | Used By |
| --- | --- | --- |
| UI barrel | `frontend/src/components/ui/index.ts` | Shared import entry |
| `Button` | `frontend/src/components/ui/button.tsx` | Tooltips, controls, panels |
| `Avatar` group | `frontend/src/components/ui/avatar.tsx` | User/avatar displays |
| `Collapsible` | `frontend/src/components/ui/collapsible.tsx` | `ToolFallback` |
| `Dialog` | `frontend/src/components/ui/dialog.tsx` | Modal/dialog surfaces |
| `Tooltip` | `frontend/src/components/ui/tooltip.tsx` | `AppShell`, layout provider, tooltip buttons |

## i18n

| Module | File | Used By | Purpose |
| --- | --- | --- | --- |
| Public i18n API | `frontend/src/lib/i18n.ts` | Pages/components | `getDictionary`, `normalizeLocale`, locale exports |
| i18n types | `frontend/src/i18n/types.ts` | i18n modules | `AppLocale`, `Dictionary`, supported locales |
| Dictionary registry | `frontend/src/i18n/dictionaries.ts` | `lib/i18n.ts` | locale file aggregation |
| Locale files | `frontend/src/i18n/locales/*.ts` | dictionary registry | app-wide nav/common/shell/chat/calendar/timeline/settings/auth copy |
| Landing i18n | `frontend/src/i18n/landing/*` | Landing page/content | landing-only copy and locale resolver |
| Login i18n | `frontend/src/i18n/login/*` | Login page | login-only copy and tool card data |

## UI-Facing API Routes

| API Route | File | Called By |
| --- | --- | --- |
| `/api/chat` | `frontend/src/app/api/chat/route.ts` | `Assistant` chat transport |
| `/api/chat/threads` | `frontend/src/app/api/chat/threads/route.ts` | `ChatThreadSidebar` / chat workspace |
| `/api/chat/threads/[threadId]` | `frontend/src/app/api/chat/threads/[threadId]/route.ts` | thread rename/delete UI |
| `/api/import/preview` | `frontend/src/app/api/import/preview/route.ts` | `ImportEntryPanel` |
| `/api/import/commit` | `frontend/src/app/api/import/commit/route.ts` | `ImportEntryPanel` |
| `/api/mobility/plan` | `frontend/src/app/api/mobility/plan/route.ts` | mobility planning tools |
| `/api/mobility/schedule` | `frontend/src/app/api/mobility/schedule/route.ts` | `MobilityPanel` |
| `/api/sync/google-calendar` | `frontend/src/app/api/sync/google-calendar/route.ts` | `CalendarLiveSync`, `GoogleCalendarSyncPanel` |
| `/api/settings/*` | `frontend/src/app/api/settings/*` | Settings panels |
| `/api/backend/health` | `frontend/src/app/api/backend/health/route.ts` | `IntegrationStatusPanel` |
| `/api/backend/chat-capabilities` | `frontend/src/app/api/backend/chat-capabilities/route.ts` | `IntegrationStatusPanel` |

## Barrel Export Map

| Barrel | Exports |
| --- | --- |
| `frontend/src/components/ui/index.ts` | avatar, button, collapsible, dialog, tooltip |
| `frontend/src/components/settings/index.ts` | settings panel components |
| `frontend/src/components/timeline/index.ts` | timeline day grid, event card, side panel |
| `frontend/src/components/mobility/index.ts` | mobility api, sections, types |
| `frontend/src/components/landing/index.ts` | landing page content |
| `frontend/src/i18n/landing/index.ts` | landing copy, resolver, types |
| `frontend/src/i18n/login/index.ts` | login copy, connected tools, types |

## Quick Ownership Guide

- 画面全体のレイアウトを変える: `frontend/src/app/*/page.tsx` と対応する top-level component を確認する。
- 共通ナビ/ページ枠を変える: `frontend/src/components/app-shell.tsx`。
- トップページの見た目を変える: `frontend/src/components/landing/landing-page-content.tsx`。
- トップページ文言を変える: `frontend/src/i18n/landing/copies.ts`。
- ログイン画面文言を変える: `frontend/src/i18n/login/copy.ts`。
- アプリ内共通文言を変える: `frontend/src/i18n/locales/*.ts` と `frontend/src/i18n/types.ts`。
- 設定画面の項目を変える: `frontend/src/app/settings/page.tsx` と `frontend/src/components/*-panel.tsx`。
- タイムライン/移動 UI を変える: `frontend/src/components/timeline/*`, `frontend/src/components/mobility-*`, `frontend/src/components/mobility/*`。
- Chat の入力・メッセージ UI を変える: `frontend/src/components/thread.tsx`、定型文は `frontend/src/components/thread-prompt-templates.ts`。
