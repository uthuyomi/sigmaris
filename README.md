# ShiftPilotAI

ShiftPilotAI の開発用ドキュメント入口です。

このリポジトリでは、実装だけでなく、判断理由や仕様メモも `docs/` 配下に残す前提で運用します。  
将来的に Notion へ移行することを想定し、Markdown の段階からページ分割しやすい構成にしています。

## ドキュメント構成

- [docs/README.md](/d:/souce/ShiftPilotAI/docs/README.md): ドキュメント全体の目次と運用ルール
- [docs/project-overview.md](/d:/souce/ShiftPilotAI/docs/project-overview.md): プロジェクト概要
- [docs/requirements/README.md](/d:/souce/ShiftPilotAI/docs/requirements/README.md): 要件・仕様の整理
- [docs/design/README.md](/d:/souce/ShiftPilotAI/docs/design/README.md): 設計メモ
- [docs/decisions/README.md](/d:/souce/ShiftPilotAI/docs/decisions/README.md): 意思決定記録
- [docs/operations/README.md](/d:/souce/ShiftPilotAI/docs/operations/README.md): 運用ログ・作業記録

## 開発環境

- フレームワーク: `Next.js 16`
- 言語: `TypeScript`
- スタイル: `Tailwind CSS`

## 開発コマンド

- 開発サーバー: `npm run dev`
- Lint: `npm run lint`
- 本番ビルド: `npm run build`

## 運用方針

- 新しい実装や仕様変更を始める前に、必要なら要件か設計メモを追加する
- 実装後は、変更内容だけでなく理由と未解決事項も残す
- 継続タスクは運用ログや意思決定記録に残し、次回判断の材料にする
- 1トピック1ファイルを基本にして、あとで Notion の1ページに移し替えやすくする

## Notion へ移行するときの想定

Markdown のファイル構成を、そのまま Notion の親子ページ構成に対応させます。

- `README.md`: リポジトリ入口ページ
- `docs/README.md`: ドキュメントホーム
- `docs/project-overview.md`: プロジェクト概要ページ
- `docs/requirements/`: 要件ページ群
- `docs/design/`: 設計ページ群
- `docs/decisions/`: 判断履歴ページ群
- `docs/operations/`: 進行ログページ群

仕組み的には、最初から粒度を揃えておくのがミソだね。あとで Notion に移しても迷子になりにくいってわけさ。
