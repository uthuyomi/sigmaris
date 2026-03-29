# 2026-03-29 Icon-First Multilingual UI

## Decision
- Shift the signed-in app toward an icon-first layout with minimal visible labels.
- Store the user language in `profiles.locale` instead of a client-only setting.
- Keep translations compact and focused on shell-level UX first.

## Reason
- The product is used through repeated daily interactions, so recognition speed matters more than verbose copy.
- A profile-backed locale is required if settings should survive devices and sessions.
- The current app already relies on server-rendered authenticated pages, so server-side locale resolution fits the existing architecture.

## Impact
- A new Supabase migration is required before language switching works in production.
- App shell, chat, calendar, timeline, and settings components now depend on a shared i18n layer.
- The UI now favors icon navigation, badges, counts, and time blocks over long labels.
