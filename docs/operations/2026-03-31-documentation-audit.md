# 2026-03-31 Documentation Audit

## 目的

このページは、会話ログと現行実装を照合して、docs の漏れを補完した時の監査メモだよ。  
既存ページを捨てるのではなく、上から追える総覧と不足ページを足して、Notion に移しやすい形へ整えるのが狙いだった。

## 監査対象

- `docs/` の既存ページ
- `frontend/` の実装構成
- `backend/` の route / service 構成
- `supabase/migrations/`
- 会話で決めた運用・設定・責務分離の内容

## 補完したページ

### 入口 / 総覧

- `docs/notion-page-map.md`

### 設計

- `docs/design/backend-endpoint-catalog.md`
- `docs/design/settings-and-preferences.md`
- `docs/design/supabase-migration-map.md`

### ログ

- `docs/operations/2026-03-31-documentation-audit.md`

## 入口ページの補強

次の index を更新して、新しい総覧ページへ導線を追加した。

- `docs/README.md`
- `docs/design/README.md`
- `docs/operations/README.md`
- `docs/project-overview.md`

## 今回補った主な漏れ

### backend endpoint 群の一覧化

会話では backend へ責務を寄せていく話をかなりしていたけど、`どの endpoint が何を担当しているか` の一覧ページが薄かった。  
そこで `backend-endpoint-catalog` を追加して、chat / Google / mobility / import / app data の各 route をまとめた。

### 設定項目の保存先と利用先

言語、AI 口調、Google カレンダー同期、自宅、保存地点、既定移動手段は会話では細かく決めていたけど、設定値と保存先の対応表が docs になかった。  
そこで `settings-and-preferences` を追加して、`profiles` や `saved_locations` と UI / backend との接点を整理した。

### migration と機能の対応

会話では `profiles.locale does not exist` みたいな migration 未適用起因のトラブルが出ていた。  
あとで見返してもすぐ分かるように、`supabase-migration-map` で migration と機能の対応を固定化した。

### Notion 配置図

docs を Notion に移す前提だったので、親ページ構成と子ページ構成が一目で分かる配置図を追加した。  
これは docs の入口としても使えるし、実際の移行作業でもそのまま下書きになる。

## まだ残している前提

- 既存の古い途中経過ページは削除していない
- 既存 markdown の一部は途中段階のメモも含む
- 今回の監査は、それらを上から追えるようにする補完中心

## 今後の運用

- 新しい backend route を足したら `backend-endpoint-catalog` に追記する
- 新しいプロフィール項目を足したら `settings-and-preferences` に追記する
- 新しい migration を足したら `supabase-migration-map` に追記する
- 大きな方向転換は `decisions/` にも残す

## 補足

今回の docs 補完で、会話ベースで積み上げてきた内容と、実装済みの構成がだいぶつながった。  
ここまで揃っていれば、Notion に移した後も「どこを見ればよいか」で迷いにくくなるはずだよ。
