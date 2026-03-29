# Icon-First Multilingual UI

## Goal
- Reduce dependency on visible text.
- Keep primary navigation recognizable through shape, icon, and placement.
- Allow the signed-in app to switch languages from settings without changing routes.

## Current Structure
- Top navigation uses icons with tooltip labels on desktop.
- Bottom navigation uses icons only on mobile.
- Chat keeps text mainly inside the conversation itself.
- Calendar uses counts, blocks, and time labels as the main visual language.
- Settings acts as the control center for sync and language.

## Language Model
- Locale is stored on `profiles.locale`.
- Supported locale values:
  - `ja`
  - `en`
  - `ko`
  - `zh-CN`
  - `zh-TW`
  - `es`
  - `fr`
  - `de`
  - `pt-BR`
  - `it`
  - `id`
  - `th`
  - `vi`
- UI dictionaries are resolved server-side and passed into page-level components.

## UX Rules
- Icons should identify the page before the label is read.
- Text should stay short and mostly secondary.
- Navigation labels are exposed through tooltips and accessibility labels, not large visible captions.
- Settings keeps the longest text because configuration is inherently more language-heavy.

## Follow-up
- Extend translation coverage beyond the compact shell dictionary when more screens grow.
- Add locale-aware server formatting for more date and event detail text.
- Revisit route planning text so it follows the same compact multilingual strategy.
