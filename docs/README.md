# Docs

このページは、`docs/` 配下のドキュメント入口です。  
あとで Notion に移すことを前提に、カテゴリごとにページを分けて管理します。

## 目次

- [project-overview.md](/d:/souce/ShiftPilotAI/docs/project-overview.md): プロジェクトの目的、スコープ、現状整理
- [requirements/README.md](/d:/souce/ShiftPilotAI/docs/requirements/README.md): 要件、仕様、ユースケース
- [design/README.md](/d:/souce/ShiftPilotAI/docs/design/README.md): 設計方針、構成、実装メモ
- [decisions/README.md](/d:/souce/ShiftPilotAI/docs/decisions/README.md): 重要な判断と理由の記録
- [operations/README.md](/d:/souce/ShiftPilotAI/docs/operations/README.md): 作業ログ、引き継ぎ、未解決事項

## 運用ルール

- 1つのテーマにつき1ファイルを基本にする
- 仕様を決める前後で、要件と設計のどちらに書くべきかを分ける
- 重要な判断は、結論だけでなく理由と影響範囲も残す
- 作業ログには、次回再開時に困らない粒度で経緯を書く
- ファイル名は、Notion のページ名にそのまま転記できるように意味が分かるものにする

## Notion 移行を見据えた考え方

- `docs/README.md` を Notion の親ページにする
- 各サブフォルダをデータベースまたは子ページ単位として扱う
- 各 Markdown ファイルを 1ページとして移行する
- 判断履歴は `decisions/` に寄せておくと、あとで一覧化しやすい

## 初期メモ

- 2026-03-27: `docs/` ディレクトリを作成
- 2026-03-27: README と docs 構成を日本語化し、Notion 移行しやすい形へ整理
