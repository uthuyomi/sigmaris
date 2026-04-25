# Notion ページ配置図

## 目的

このページは、`docs/` をそのまま Notion に移す時に、どのページを親にして、どの詳細ページを子にぶら下げるかを整理するための配置図だよ。  
会話で積み上げた履歴を落とさずに移し替えるには、`概要 -> 要件 -> 設計 -> 判断 -> 作業ログ` の順に親ページを切るのが一番追いやすい。

## 推奨トップ階層

1. プロジェクト概要
2. 要件
3. 設計
4. 判断記録
5. 作業ログ

## 1. プロジェクト概要

親ページ候補:

- `docs/project-overview.md`

子ページ候補:

- `docs/notion-page-map.md`
- `docs/README.md`

## 2. 要件

親ページ候補:

- `docs/requirements/README.md`

子ページ候補:

- `docs/requirements/product-scope.md`
- `docs/requirements/time-based-scheduling.md`

## 3. 設計

親ページ候補:

- `docs/design/README.md`

子ページ候補は、Notion 側ではさらに次の小見出しに分けると扱いやすい。

### 3-1. 全体設計

- `docs/design/system-architecture.md`
- `docs/design/frontend-architecture.md`
- `docs/design/backend-api-architecture.md`
- `docs/design/backend-chat-stream.md`
- `docs/design/backend-endpoint-catalog.md`

### 3-2. データ / 認証 / 設定

- `docs/design/supabase-schema.md`
- `docs/design/supabase-migration-map.md`
- `docs/design/supabase-google-auth.md`
- `docs/design/settings-and-preferences.md`
- `docs/design/chat-thread-persistence.md`

### 3-3. UI / UX

- `docs/design/chat-ui-and-design-system.md`
- `docs/design/chat-implementation.md`
- `docs/design/page-structure.md`
- `docs/design/initial-ui-implementation.md`
- `docs/design/timeline-interaction-spec.md`
- `docs/design/icon-first-multilingual-ui.md`
- `docs/design/login-and-entry-flow.md`

### 3-4. Google / import / mobility

- `docs/design/google-integration-implementation.md`
- `docs/design/chat-google-tools.md`
- `docs/design/import-pipeline.md`
- `docs/design/mobility-planning.md`
- `docs/design/travel-block-scheduling.md`

## 4. 判断記録

親ページ候補:

- `docs/decisions/README.md`

運用としては、Notion では日付 DB にして、カテゴリ列を持たせると見返しやすい。

推奨カテゴリ:

- 初期方針
- UI / UX
- Google 連携
- import
- mobility
- データ / backend

## 5. 作業ログ

親ページ候補:

- `docs/operations/README.md`

子ページ候補:

- `docs/operations/2026-03-27-work-log.md`
- `docs/operations/2026-03-29-work-log.md`
- `docs/operations/2026-03-31-comprehensive-log.md`
- `docs/operations/2026-03-31-documentation-audit.md`

## Notion 化のコツ

- `README.md` 系は Notion の親ページ本文に貼る
- 個別の詳細 markdown は子ページとしてそのまま流し込む
- `decisions/` は日付 DB 化すると比較しやすい
- `operations/` は時系列 DB にすると handover しやすい
- `design/` は固定ページのほうが向いている

## 補足

今回の docs 補完では、既存の途中経過メモを消すのではなく、上から追える索引と総覧ページを追加する方針を取っている。  
Notion でも同じ考え方で、古いメモは残しつつ、入口ページで導線を整理するのが安全だよ。
