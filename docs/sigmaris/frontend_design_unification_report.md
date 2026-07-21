# フロントエンド デザイン統一 第一段階（トークン整理 ＋ 共有UIコンポーネント抽出）実施報告

**実施日**: 2026-07-21
**関連**: `docs/sigmaris/frontend_inventory_2026.md`（棚卸し 5.1・5.2）
**ブランチ**: `design-unify-tokens-shared-ui`（`main` `1d87a23` から作成）
**採用方針（運用者の選択）**: **「Cパターン：安全な範囲のみ先行」**。
> 実装前に、依頼書の「本文で `bg-background` 等のCSS変数トークンを使う（要件1）」と「light/darkを正しく切り替える（要件2）」を同時に満たすには `globals.css` の `:root` に light 値を投入する必要があるが、**`/chat` 自身のコンポーネント（`markdown-text.tsx`・`tool-fallback.tsx`・`ui/*`）が同じトークン（`bg-muted`・`bg-popover`・`bg-background`）を使用している**ため、`:root` を light 化すると light テーマ時に `/chat` のコード表示・ツールチップ・ダイアログが明色化し、**`/chat` のダークデザインが崩れる（要件4に抵触）**ことをコードで確認した。この競合は棚卸しでは見えていなかったため運用者に確認し、**「Cパターン：安全な範囲のみ先行」**の指示を得た。本タスクはこれに従い、**土台の整理（トークン化＋共有部品抽出）までに留め、light/darkの本文切替の"有効化"は第二段階へ申し送る**。

---

## 1. デザイン方向性の明文化（Linear / Claude.ai / Vercel の共通原則）

今後の統一作業の参照基準として、3つの参照先に共通する原則を簡潔にまとめる。

| 原則 | 内容 | 本コードベースへの含意 |
|---|---|---|
| **余白を大胆に** | 要素を詰め込まず、周囲に十分な空白を取る。密度より呼吸感 | カード内パディング・セクション間の間隔を広めに取る。「カードがびっしり並ぶ事務的な印象」を避ける |
| **装飾を削る** | 影・枠線・グラデーション等の視覚ノイズを最小化。境界は淡く | 濃い枠線や強い影を避け、淡い境界（`border-border` = 白10%）で区切る |
| **情報を絞る** | 1画面/1セクションに詰め込む情報量を抑え、階層を明確化 | セクション見出し＋説明文で意図を明示し、詳細は折りたたむ（既存の `Collapsible` 活用方針を踏襲） |
| **静かな配色** | 彩度を抑えたニュートラル基調＋最小限のアクセント1色 | ニュートラル（背景/カード/前景/ミュート）＋アクセント（`--primary` = `#9b59b6`）1色という既存トークン構成はこの原則に合致 |
| **タイポで階層を作る** | 色や罫線ではなく、文字サイズ・ウェイト・字間で情報階層を表現 | 見出し `font-semibold`／本文 `text-muted-foreground`、字間 `tracking-tight/wide` の使い分けを共有部品に集約 |

本第一段階では、この方針に沿って**共有部品のパディング・行間をやや広げる微調整**のみ加えた（大きな構造変更はしていない。例: セクション `p-4 sm:p-5` → `p-5 sm:p-6`、セクション間 `gap-4` → `gap-5`、ヒーロー `px-5 py-6` → `px-6 py-7`）。

---

## 2. トークン化した箇所の一覧

hex 直書き → 既存 CSS 変数トークンへの対応（`globals.css` で定義済みのものを使用。新規トークンは作っていない）。

| 旧 hex | 新トークン | 用途 | 備考 |
|---|---|---|---|
| `#212121` | `bg-background` / `text-*` は `text-foreground` | ページ本文コンテナ・アイテムカード背景 | `--background` と同値（現状ダーク） |
| `#2f2f2f` | `bg-card` | ヒーローカード背景 | `--card` と同値 |
| `#2a2a2a` | `bg-card` | セクションカード背景 | **厳密同値のトークンが無いため `#2f2f2f`(`bg-card`) へ寄せた微小な色差**（依頼書が許容する範囲） |
| `#ececec` | `text-foreground` | 主要テキスト | `--foreground` と同値 |
| `#8e8ea0` | `text-muted-foreground` | 補助テキスト・ラベル | `--muted-foreground` と同値 |
| `#d8d8de` | `text-foreground/85` | 本文値テキスト | 近似（僅かな明度差） |
| `#cfcfd7` | `text-foreground/85` / `text-muted-foreground` | 小見出し | 近似 |
| `#9b59b6` | `bg-primary` / `text-primary-foreground` / `border-primary` / `bg-primary/10` 等 | 進捗バー・アクセント・自己反省ボタン・自己モデル引用枠 | `--primary` と同値 |
| `#ad6bc7` | `bg-primary/85`（hover） | ボタンhover | 近似 |
| `#f1e8f6` | `text-foreground` | 自己モデル引用テキスト | 近似 |
| `#6f6f7a` | `text-muted-foreground/70` | Drive注記 | 近似 |
| `border-white/10` | `border-border` | 全枠線 | `--border` = 白10% と同値 |

**据え置いた hex（意図的・第二段階で検討）**:
- `#e07856`（＋`#e0a088`）… 「注意」を表すセマンティックなオレンジ（growth の StatusBadge、timeline のTTL超過インジケーター）。既存トークンに対応が無く、`--destructive`(赤)へ寄せると意味が変わるため据え置き。
- Recharts の JS プロパティ内の色（`fill`/`stroke`/`contentStyle` の `#9b59b6`・`#8e8ea0`・`#2a2a2a`・`#ececec` 等、`event-volume-chart.tsx`・`trend-line-chart.tsx`）… Tailwind クラスではなく SVG/インラインスタイル値で、CSS変数化には computed style 読み取りが必要なため「安全な範囲」外として据え置き。
- `bg-white/[0.03]`・`bg-white/[0.06]`・`bg-white/10`・`bg-white/[0.04]`（EmptyState/Badge/進捗トラック等の白アルファ）… 既存の globals.css 補正（`.dark [class*="bg-white/"]`）で吸収される薄い重ね色で、そのまま維持。
- `frontend/src/components/live/*`（LiveDashboard 内部）の hex … 表示部品の抽出対象外。第二段階で扱う。

**対象ファイル**: `frontend/src/app/{memory,timeline,growth,live}/page.tsx`、`frontend/src/components/timeline/state-history-disclosure.tsx`。

---

## 3. light/dark 両テーマの確認結果

**重要（正直な記載）**: 本タスクは「Cパターン：安全な範囲のみ先行」を採用したため、**light/dark の本文切替を"有効化"する変更（`:root` への light 値投入等）は行っていない**。したがって現時点の挙動は**変更前と同じ**である:

- chrome（`AppShell` のヘッダー・ナビ）: light/dark で切り替わる（従来通り）。
- 本文（`/memory`・`/timeline`・`/growth`・`/live`）: `bg-background`/`bg-card` 等のトークンは**現状 `:root` と `.dark` が同値（ダーク）**のため、テーマに関わらずダーク表示（従来の hex 直書きと同じ結果）。

**つまり本段階の意義は「見た目を変えずに、テーマ切替を将来効かせられる土台へ置き換えた」こと**である。第二段階で `:root` に light パレットを投入し、`/chat` を保護すれば、これらの本文は**変更不要で**自動的に light/dark 両対応になる（トークン参照済みのため）。

**ブラウザでの目視確認は未実施**。実 Supabase 認証・本番相当バックエンドが必要で、依頼書の注意事項（サーバーアクセス・APIキー追加取得は試みない）に従った。代わりに以下の静的検証で「見た目が大きく崩れていない」ことを担保した:
- トークンは現状ダーク値と同値／近似のため、レンダリング結果は現行とほぼ同一（§2の微小色差・余白微調整を除く）。
- `next build` の静的生成・型検査を通過（§5）。
- `/chat`・`globals.css`・`app-shell.tsx`・`sigmaris-sidebar.tsx` は**一切変更していない**（`git status` で確認）ため、`/chat` の外観への影響は原理的に無い。

---

## 4. 抽出した共有コンポーネントの一覧・配置場所

**配置**: 新設 `frontend/src/components/shared/`（`dashboard-ui.tsx` ＋ バレル `index.ts`）。

| コンポーネント | 役割 | 旧・重複していた場所 |
|---|---|---|
| `PageHero` | Σアバター＋タイトルのページ先頭ヒーローカード | `/memory`・`/timeline`・`/growth`・`/live` に各々インライン（4重複） |
| `Section` | 見出し＋説明＋任意アクションのセクションカード | `/memory`・`/timeline`・`/growth` にインライン（3重複） |
| `Badge` | 丸角バッジ | `/memory`・`/timeline` にインライン（2重複） |
| `ConfidenceBar` | 0〜1を進捗バー表示（内部で clamp） | `/memory`・`/timeline` にインライン（2重複） |
| `EmptyState` | 空状態表示 | `/memory`・`/timeline`・`/growth` にインライン（3重複） |
| `ErrorState` | エラー表示（セマンティック赤は据え置き） | `/memory`・`/timeline`・`/growth` にインライン（3重複） |

- 各ページから重複インライン定義を**削除し、共有コンポーネントを import** する形へ書き換えた。差分は **−305 / +128 行（正味 約−177行）** で、重複解消による純減。
- **ページ固有で重複していなかった部品**（growth の `StatCard`・`DriveLevelBar`・`StatusBadge`、timeline の `EventDecayIndicator`）は共有化せず各ページに残し、色のトークン化のみ行った（不要な共有化を避ける判断）。
- `ConfidenceBar` は従来 `/memory` がローカル `clampConfidence`、`/timeline` が `lib/timeline/transform` の `clampConfidence` を使う二重実装だったが、共有版に clamp を内包して一本化した（挙動は同一）。

---

## 5. テスト結果

| 検証 | 結果 |
|---|---|
| `npx eslint .`（frontend） | **0 件**（警告・エラーなし） |
| `npx next build`（frontend, クリーンビルド） | **成功**。`✓ Compiled successfully` ／ 型検査通過。ルート一覧に `/chat`・`/memory`・`/timeline`・`/growth`・`/live`・`/settings`・`/admin/memory`・`/legal/*` 等が全て残存 |
| `pytest tests/`（backend, 既存16件） | **16 passed**（リグレッションなし。本タスクはフロントのみのため影響なしを確認） |
| light/dark 目視（ブラウザ） | **未実施**（§3。サーバー/実データが必要なため。第二段階で要確認） |

> フロントエンドには自動テストランナーが存在しないため、上記のビルド成功・Lintクリーンを検証の中心に据えた（既存の運用と同じ）。

---

## 6. 気づいた懸念点・次のステップ（ナビ一本化・役割整理）への申し送り

### 6.1 第二段階（light/dark の"有効化"）で必ず対処すべきこと
1. **`:root` に light パレットを投入する**（`.dark` は現行ダークを維持）。棚卸しの通り AppShell/settings が既に使う light 値（`#f7f7f8`・白・`stone-*`）を流用すると、出荷済みの見た目と整合が取りやすい。
2. **`/chat` の保護が必須**。`/chat` の `markdown-text.tsx`・`tool-fallback.tsx`・`ui/*` は `bg-muted`/`bg-popover`/`bg-background` トークンを使うため、`:root` を light 化すると light テーマ時に `/chat` 内のコードブロック・テーブル・ツールチップ・ダイアログが明色化して崩れる。`/chat` のサブツリーを常にダークトークン文脈に固定する措置（例: chat コンテナに `dark` スコープを与える、または `.chat-thread-surface` にダークトークンを再定義する）を、`/chat` の外観を変えない形で入れること。
3. **`body`/`html` のダーク固定の見直し**。`globals.css` の `html/body { background:#212121; color:#ececec; color-scheme:dark }` はテーマ非依存でダーク固定。light を効かせるにはここをトークン参照＋`color-scheme` のテーマ連動へ変更する必要がある（影響範囲が広いため、必ずブラウザで全ページ確認すること）。
4. **ブラウザでの light/dark 目視確認**（`/memory`・`/timeline`・`/growth`・`/live` ＋ `/chat` が light テーマで崩れないこと）。本段階では実施できていない。

### 6.2 残りのトークン化（第二段階以降）
- Recharts の JS プロパティ色（§2）。CSS変数を computed style 経由で読むヘルパを用意すれば、チャットと同じアクセントで light/dark 追従できる。
- `frontend/src/components/live/*`（LiveDashboard 内部）の hex。/live 本文の大半はここにあるため、要件1（/live 本文のトークン化）を完全に満たすには本コンポーネント群の移行が必要。
- セマンティックな「注意」オレンジ `#e07856` … `--warning` 系トークンを1つ新設するかどうかを検討（現状は新規トークン抑制のため据え置き）。

### 6.3 ナビ一本化・役割整理（棚卸し §5.3–5.4 の続き）への申し送り
- 共有 `PageHero`/`Section` が揃ったので、次段でナビを一本化する際、`/live` を `AppShell` に載せる／`/admin/memory` を `/timeline` のタブへ統合する等の再構成が、**各ページの表示部品を触らずに**進めやすくなった。
- `#2a2a2a`→`bg-card` へ寄せたことで、セクション背景とヒーロー背景が同一（`#2f2f2f`）になった。もし階層の差を付けたい場合、第二段階で `--surface` 系トークンを1つ足すか、`bg-card` に淡い枠/影で差を付けるのが「装飾控えめ」方針と両立する。

---

## 7. 変更ファイル一覧

| ファイル | 変更 |
|---|---|
| `frontend/src/components/shared/dashboard-ui.tsx` | **新規**。共有UI部品6種（トークンベース） |
| `frontend/src/components/shared/index.ts` | **新規**。バレルエクスポート |
| `frontend/src/app/memory/page.tsx` | 共有部品import＋hexトークン化 |
| `frontend/src/app/timeline/page.tsx` | 同上（`EventDecayIndicator` はローカル維持・トークン化） |
| `frontend/src/app/growth/page.tsx` | 同上（`StatCard`/`DriveLevelBar`/`StatusBadge` はローカル維持・トークン化） |
| `frontend/src/app/live/page.tsx` | ヒーローを `PageHero` へ、コンテナをトークン化 |
| `frontend/src/components/timeline/state-history-disclosure.tsx` | hexトークン化 |

**変更していない（意図的）**: `frontend/src/app/globals.css`、`frontend/src/app/chat/**`、`frontend/src/components/chat-workspace.tsx`、`frontend/src/components/sigmaris-sidebar.tsx`、`frontend/src/components/app-shell.tsx`。

---

*本報告は実施内容の記録である。light/dark の本文切替"有効化"は、`/chat` 保護とブラウザ目視を伴う第二段階として明示的に申し送った。*

---

# 第二段階（light/dark の本格対応）実施報告

**実施日**: 2026-07-21
**ブランチ**: `design-unify-light-dark`（`main` の第一段階マージ後 `379cb02` から作成）
**目的**: (1) `:root` に light パレット投入、(2) `/chat` を常時ダークに保護、(3) `body`/`html` のダーク固定見直し。これにより `/memory`・`/timeline`・`/growth`・`/live` が light/dark 両対応になり、`/chat` は常に既存のダークを保つ。

## 8. テーマ機構の把握（着手前の調査）

実装前に、現行のテーマ適用機構をコードで確認した（これが `/chat` 保護方針を決めた根拠）:

- **テーマは `<html>` の `.dark` クラスで制御される。** `app/layout.tsx` が SSR で常に `<html className="... dark ...">` を出力（＝初期状態は常にダーク）。`components/app-shell.tsx` の `useEffect` が `document.documentElement.classList.toggle("dark", theme === "dark")` で、ユーザーのテーマ設定に応じて `.dark` を付け外しする。
- 従来 `:root` と `.dark` が同値（ダーク）だったため、light テーマ（`.dark` 除去）でも本文はダークのままだった。

**ブラスト半径の確認（`:root` を light 化して影響が出る範囲）**: トークン（`bg-background`/`bg-card` 等）を使うファイルを grep した結果、影響を受けるのは (a) 第一段階でトークン化した4ページ（＝意図通り light 化）、(b) `/chat` のレンダリング部品（`markdown-text`・`tool-fallback`・`ui/*`）＝保護対象、(c) `timeline/state-history-disclosure`（timeline内）のみ。**`/`・`/login`・`/launch`・`/legal`・`/settings`・`/admin/memory` はトークンを直接使っておらず**、各々が自前で背景を持つ（`/`=`#212121`ダーク、`/login`・`/legal`=クリーム系ライト）ため、`:root` 変更の影響を受けない（コードで確認）。→ ブラスト半径は限定的で安全と判断。

## 9. `:root` への light パレット投入の実装詳細

`frontend/src/app/globals.css`:
- **`:root` を light パレットへ変更**（`.dark` は既存ダークを維持し、`color-scheme` を各々へ付与）。値は**新規に作らず、既に出荷済みで動作実績のある AppShell の light-first 配色を採用**（依頼書「既存資産を最大限活用」）:

| トークン | :root（light） | .dark（dark・維持） |
|---|---|---|
| `--background` | `#f7f7f8` | `#212121` |
| `--foreground` | `#1c1917` | `#ececec` |
| `--card` / `--popover` | `#ffffff` | `#2f2f2f` |
| `--muted` / `--secondary` / `--accent` | `#f5f5f4` | `#2f2f2f` |
| `--muted-foreground` | `#78716c` | `#8e8ea0` |
| `--border` | `rgb(28 25 23 / 10%)` | `rgb(255 255 255 / 10%)` |
| `--primary` | `#9b59b6`（両テーマ共通のブランド色） | `#9b59b6` |
| `color-scheme` | `light` | `dark` |

- 第一段階の共有部品・4ページはこれらのトークンを使っているため、**追加のページ変更なしで**自動的に light/dark 追従になった。
- **light で不可視になる箇所を補正**: バッジ背景・進捗トラック・空状態の白アルファ（`bg-white/x`）は light 背景上でほぼ不可視のため `bg-muted`/`bg-muted/50` へ変更（dark では従来と同等の見え方、light では視認可能）。エラー文字色（`text-red-100`）・成長ステータスの emerald/オレンジ文字色は light で低コントラストになるため `text-red-700 dark:text-red-100` のようにテーマ対応にした。
- スクロールバーのつまみ（従来 白18%固定・light で不可視）を中立グレー `rgb(120 120 130 / 40%)` へ変更（両テーマで視認可）。

## 10. `/chat` の保護の実装方法・判断根拠（最重要）

`/chat` を「常にダークトークン文脈」に固定するため、**二重の保護**を最小限の変更で入れた。

1. **`ChatWorkspace` ルート要素に `.dark` クラスを付与**（`components/chat-workspace.tsx`、依頼書が推奨した方式）。このサブツリー全体が、html の状態に関わらず `.dark` のトークンを解決する。SSR/初回描画・画面遷移直後の一瞬でも、チャット本文・サイドバー・コードブロック等の**トークン利用要素がダークのまま**描画される。
2. **`/chat` の AppShell に `theme="dark"` を渡す**（`app/chat/page.tsx`、1点のみ）。テーマは `<html>.dark` で制御されるため、これにより light ユーザーが `/chat` を開いている間も `html.dark=true` が維持される。**理由**: Copy ボタンのツールチップ等は Radix ポータルで `<body>` 直下（＝`ChatWorkspace` の `.dark` サブツリーの外）に描画されるため、(1) だけでは覆えない。`<html>.dark` を維持すれば、ポータル要素も `<html>` 配下として `.dark` 文脈に入り、確実にダークになる。

**判断根拠（なぜ両方か）**: (1) は本文サブツリーを SSR から即座にダート化するが**ポータルを覆えない**。(2) はポータル含め `<html>` 単位でダート化するが、クライアント遷移直後の1フレームだけ `useEffect` 適用前に本文がライトになりうる。両者を組み合わせることで**フラッシュもポータル漏れもなく**、`/chat` の見た目を現行のダークのまま完全に保つ。`/chat` 側のファイル変更は **`chat/page.tsx` の `theme` 指定1点** と **`chat-workspace.tsx` の className に `dark` を1語追加**のみ（依頼書「/chat ファイル変更は最小限」）。**`/chat` の視覚デザインには一切変更を加えていない**（ダークのまま）。

## 11. `body`/`html` の見直し内容

- `globals.css`: `html { background: #212121 }` → `background: var(--background)`。`body` から `background:#212121; color:#ececec; color-scheme:dark` の固定を撤去（背景/文字色は `@layer base` の `bg-background/text-foreground` トークンに委譲、`color-scheme` は `:root`/`.dark` へ移動）。
- `app/layout.tsx`: `<body className="... bg-[#212121] text-[#ececec]">` → `bg-background text-foreground`（テーマ追従）。`<html>` の SSR `dark` クラスは**維持**（初期状態をダートにし、AppShell が light ページでのみ外す設計を踏襲。トークン非依存で自前背景を持つ `/`・`/login`・`/legal` 等はこの変更の影響を受けない）。

## 12. light/dark 両テーマでの確認結果（`/chat` 非影響の確認を含む）

**静的検証・コード上の帰結による確認**（ブラウザ目視は §13 の通り未実施）:
- `/memory`・`/timeline`・`/growth`・`/live`: トークン参照済みのため、`html.dark` の有無で `:root`(light)/`.dark`(dark) が切り替わり、本文が light/dark で切り替わる。light で不可視化する白アルファ・低コントラスト文字は §9 で補正済み。
- **`/chat`（最重要）**: §10 の二重保護により、ユーザーが light テーマでも `html.dark=true`（AppShell `theme="dark"`）＋ `ChatWorkspace` の `.dark` が維持され、本文・サイドバー・コードブロック・ポータル（ツールチップ）まで**すべてダーク**。`SigmarisSidebar`/`ChatWorkspace` の背景は元々ハードコード（`#171717`/`#212121`）で不変。**`/chat` の見た目は現行のダークのまま。**
- `/`・`/login`・`/launch`・`/legal`: トークン非依存・自前背景のため不変（`/` ダーク、`/login`・`/legal` クリーム）。

## 13. テスト結果

| 検証 | 結果 |
|---|---|
| `npx eslint .`（frontend） | **0 件** |
| `npx next build`（クリーンビルド） | **成功**。全ルート（`/chat`・`/memory`・`/timeline`・`/growth`・`/live`・`/settings`・`/admin/memory`・`/legal/*` 等）残存 |
| `pytest tests/`（backend, 16件） | **16 passed**（フロントのみ変更のため影響なし） |
| **ブラウザでの light/dark 目視** | **未実施**（実 Supabase 認証・実データが必要。依頼書の注意事項に従い追加アクセスは試みていない） |

## 14. 変更ファイル一覧（第二段階）

| ファイル | 変更 |
|---|---|
| `frontend/src/app/globals.css` | `:root` を light パレット化・`color-scheme` 追加、`html`/`body` のダーク固定撤去、スクロールバー中立化 |
| `frontend/src/app/layout.tsx` | `<body>` をトークン（`bg-background`/`text-foreground`）へ |
| `frontend/src/app/chat/page.tsx` | AppShell へ `theme="dark"` を渡す（/chat 保護・1点） |
| `frontend/src/components/chat-workspace.tsx` | ルート `<section>` に `dark` を1語追加（/chat 保護・サブツリー固定） |
| `frontend/src/components/shared/dashboard-ui.tsx` | 白アルファ→`bg-muted`、ErrorState 文字色をテーマ対応、コメント更新 |
| `frontend/src/app/{memory,timeline,growth}/page.tsx` | 白アルファ→`bg-muted`、StatusBadge 文字色をテーマ対応 |

**変更していない（意図的）**: `/chat` の視覚デザイン（ダークのまま）、`app-shell.tsx`、`sigmaris-sidebar.tsx`、`/settings`・`/admin/memory`・`/legal`・`/login`・`/` の各ページ、バックエンド。

## 15. 気づいた懸念点・次のステップ（ナビ一本化）への申し送り

1. **ブラウザ目視が未実施**（§13）。特に **light テーマでの `/chat`（ツールチップ含む）がダークを保つこと**、および 4ページの light 表示崩れが無いことは、実機で最終確認することを強く推奨する。設計上は §10・§12 の通り保護されているが、目視確認だけは本環境では行えていない。
2. **`/settings` は独自の light 実装**（stone/light ＋ `.settings-page` 補正）のまま。今回の `:root` light 化と二重管理になっており、次段で `/settings` もトークン方式へ寄せると一貫性が増す。
3. **Recharts の色（`event-volume-chart`・`trend-line-chart`）と `live/*` 内部の hex は据え置き**（第一段階 §6.2 の通り）。light テーマではチャートの軸ラベル（`#8e8ea0`）やツールチップ背景（`#2a2a2a`）がダーク前提のままなので、次段で CSS 変数を computed style 経由で読む対応を検討する。
4. **ナビ一本化（棚卸し §5.3）**: トークンが両テーマ対応になったので、`/live` を `AppShell` に載せる・`/admin/memory` をタブ統合する等の再構成が、配色を気にせず進めやすくなった。`/chat` だけは常時ダーク固定という制約を、ナビ設計時にも維持すること。

---

*第二段階は light/dark の本格対応を実装した。`/chat` は二重保護で常時ダークを維持する設計としたが、ブラウザ目視のみ本環境では実施できていないため、マージ前の最終目視確認を推奨する（§13・§15）。*

---

# 第三段階（ナビゲーションの一本化）実施報告

**実施日**: 2026-07-21
**ブランチ**: `design-unify-nav`（`main` の第二段階マージ後 `5285d7d` から作成）
**目的**: `/chat`（AppShell ナビ非表示・独自サイドバー）と AppShell 5項目ナビの分断を解消し、`/chat` からも `/timeline`・`/growth` へ行けるようにする。`/live` は隠しページとして明記（Step 5 でサイドバー統合予定のため、今回はナビに追加しない）。

## 16. `/chat` へのナビ追加の実装詳細

- **対象**: `frontend/src/components/sigmaris-sidebar.tsx`（`/chat` 専用の左サイドバー）。
- **変更内容**: 既存の下部リンク（`/memory`「記憶」・`/settings`「設定」）に、**`/timeline`「タイムライン」・`/growth`「成長ログ」を追加**（計4リンク）。
- **判断根拠（見た目・順序・アイコン）**:
  - AppShell の5項目タブを `/chat` にそのまま持ち込むのではなく、**`SigmarisSidebar` 既存の `SidebarLink` 様式（ダーク配色 `#171717`/`#2f2f2f`/`#ececec`、`min-h-10` の縦並びリンク）に自然に追加**する形にした（依頼書の指示通り）。→ `/chat` の既存デザイン言語を崩さない。
  - 並び順は AppShell の `navItems` と同じ **memory → timeline → growth → settings**（`/chat` 自身はこのサイドバーのロゴ/新規チャットが担うため下部リンクには含めない）。
  - アイコンは AppShell の `navIconByPath` と揃えた（**timeline = `HistoryIcon`、growth = `ActivityIcon`**）。`lucide-react` から追加 import。
  - `active` 判定・`onNavigate`（モバイルでドロワーを閉じる）は既存 `SidebarLink` の呼び出しパターンをそのまま踏襲。
- **`/chat` の視覚デザインは不変**: 追加したのは同一様式のリンク2件のみで、配色・レイアウト・トーンは既存のまま。第二段階の `/chat` 保護（`ChatWorkspace` の `.dark` ＋ `chat/page` の `theme="dark"`）にも一切触れていない。

## 17. `/live` の扱いの明記内容

- **方針決定の根拠**: 依頼書の指示通り、`/live` は「Sigmaris Live を将来 Step 5 でチャット画面のサイドバーへ統合する計画が既にある」ため、**独立ページとしてナビに恒久導線を張らず、`/admin/memory` と同様の"意図的な隠しページ"として明記**する方針を採った。独立ページとしてナビに追加してしまうと、Step 5 の統合時にナビから再削除する後戻りが発生するため、それを避ける判断。
- **実装**: `frontend/src/app/live/page.tsx` 冒頭コメントに、`/admin/memory`（`page.tsx` の "Deliberately not part of ... the main nav" の記法）を参考に、**「ナビゲーション上の位置づけ: 意図的な"隠しページ"」**の節を追記。URL直打ち（`?demo=1` のデモ用途含む）でのみ到達すること、Step 5 で扱うことを明記した。
- **本タスクでは `/live` をナビに追加していない**（要件3）。`AppShell` の `navItems`・`SigmarisSidebar` のいずれにも `/live` は無い（コードで確認）。

## 18. `/admin/memory` の扱い

- 現状の隠しページの位置づけを**維持（変更なし）**。

## 19. モバイル・スワイプ操作への影響確認

- **`AppShell`（`app-shell.tsx`）は一切変更していない**。モバイル下部ナビ（`grid-cols-5`）・左右スワイプ遷移は AppShell の `navItems` に基づくが、その `navItems` は不変。→ `/memory`・`/timeline`・`/growth`・`/settings` 等のモバイルナビ・スワイプは**影響を受けない**。
- `/chat` は `fitViewport` で AppShell の下部ナビ・スワイプハンドラを描画しないため、今回追加した `SigmarisSidebar` のリンクは通常の `<Link>` 遷移のみ。モバイルではドロワー内に表示され、タップで `onNavigate`（ドロワークローズ）→ 遷移する既存挙動に乗る。→ スワイプ等への悪影響なし。

## 20. テスト結果（第三段階）

| 検証 | 結果 |
|---|---|
| `npx eslint .` | **0 件** |
| `npx next build` | **成功**（全ルート残存） |
| `pytest tests/`（backend 16件） | **16 passed**（フロントのみ変更） |
| `/chat` → `/timeline`・`/growth` 遷移 | コード上、`SidebarLink` の `<Link href>` で到達可能（ビルド成功・型検査通過）。実ブラウザ目視は未実施（実データ要） |
| `/chat` の見た目・light/dark | 変更箇所は同一様式のリンク追加のみ。`/chat` 保護（第二段階）に未変更のため、ダーク維持は保たれる想定 |

## 21. 変更ファイル一覧（第三段階）

| ファイル | 変更 |
|---|---|
| `frontend/src/components/sigmaris-sidebar.tsx` | `/timeline`・`/growth` リンクを既存様式で追加（`HistoryIcon`/`ActivityIcon` を import） |
| `frontend/src/app/live/page.tsx` | 冒頭コメントに「意図的な隠しページ」節を追記（コードの動作は不変） |

**変更していない（意図的）**: `app-shell.tsx`（navItems 不変）、`chat-workspace.tsx`・`chat/page.tsx`（第二段階の保護を維持）、`/admin/memory`、`globals.css`、バックエンド。

## 22. 気づいた懸念点・次のステップ（Step 4: 記憶・状態ページの役割整理）への申し送り

1. **ナビ項目が増えつつある**: `/chat` サイドバーは 記憶/タイムライン/成長ログ/設定 の4リンクに、AppShell は5タブになった。Step 4 で `/memory`・`/timeline`・`/admin/memory`（同じ `user_fact_items` を別角度で見る3ページ）をタブ統合すれば、ナビ項目自体を減らせる。統合後は本ステップで追加したサイドバーリンクも見直す価値がある。
2. **`/growth` はナビ上「見る系」に同居しているが対象が別軸**（記憶ではなくシグマリス自身の健全性）。Step 4 のグルーピング（例:「記憶」「状態/内部」）で役割を明示すると混乱が減る（棚卸し §5.4）。
3. **`/live` の隠しページ扱いは Step 5 前提**。Step 5（サイドバー統合）着手時に、本コメントと `/admin/memory` の扱いを合わせて再検討すること。
4. **`/chat` 常時ダークの制約**は今後のナビ再構成でも維持すること（第二段階 §10）。サイドバーに新リンクを足す場合も、`SidebarLink` のダーク様式に合わせれば `/chat` 保護は崩れない。
5. **実ブラウザ目視は未実施**（本環境の制約）。`/chat` からの新リンク遷移とダーク維持は、本番反映後に実機確認を推奨。

---

*第三段階は `/chat` サイドバーへ `/timeline`・`/growth` を既存様式で追加し、`/live` を隠しページとして明記した。AppShell の navItems は不変でモバイル/スワイプへの影響なし。*

---

# 第四段階（「記憶・状態を見る」ページの役割整理）実施報告

**実施日**: 2026-07-21
**ブランチ**: `design-unify-memory-tabs`（`main` の第三段階マージ後 `b611487` から作成）
**目的**: 同じ `user_fact_items` を別角度で見る `/memory`・`/timeline`・`/admin/memory` の3ページを、`/memory` 1画面のタブ（現在地/変遷/生データ）へ統合し、"似た目的のページが分散"する混乱を解消する。`/growth`（シグマリス自身の健全性）は別軸のため**統合対象外・不変更**。

## 23. タブ構成の設計・判断根拠

- **統合先**: `/memory` を唯一の正となる「記憶」画面とし、`?tab=` で3タブを切り替える。
- **タブと並び順**（判断根拠: **利用者が最もよく見るものを先頭**に）:

  | 並び | タブ | key | 内容 | 対象読者 |
  |---|---|---|---|---|
  | 1 | **現在地** | `current`（既定） | 事実・傾向・自己モデル・自己物語（旧 /memory） | 利用者。最も日常的に見るため先頭 |
  | 2 | **変遷** | `timeline` | event/state/trait の時間変遷・週次グラフ・supersede履歴（旧 /timeline） | 利用者。時々振り返る |
  | 3 | **生データ** | `raw` | 記憶の鮮度・矛盾の生データテーブル（旧 /admin/memory） | 開発者/運用。最も専門的なので末尾 |

- **タブUIの設計**（依頼書「静かで自然な遷移／ダッシュボード的でない」）: AppShell ナビと同系統の**落ち着いた丸角セグメント**（`components/memory/memory-tabs.tsx`）。トークン（`bg-muted`/`bg-card`/`text-foreground`/`text-muted-foreground`）で light/dark 両対応、アクティブタブのみ `bg-card`＋淡い影で静かに浮き上がる。`?tab=` の通常 `<Link>` 遷移で、サーバー側が**該当タブの本文だけを取得・描画**する（全タブ分を毎回フェッチしない）。
- **"開発者向け"の性質の保持**（依頼書の制約）: 「生データ」タブは、タブ名に「生データ」、本文冒頭に **`開発者向け` バッジ ＋「やや専門的な運用・デバッグ向け」注記**を置き、他タブ（利用者向けの落ち着いた表示）と性質が違うことを明示。旧 /admin/memory の hex 直書き配色は、他タブと同じ light/dark トークンへ置き換えた。
- **共有部品の再利用**（依頼書の制約「作り直さない」）: 第一段階の `Section`/`Badge`/`ConfidenceBar`/`EmptyState`/`ErrorState`/`PageHero` と、既存の `EventVolumeChart`/`StateHistoryDisclosure`/`MemoryDashboardTable`/`lib/timeline/transform` をそのまま流用。本文ロジックは新規 `components/memory/{current,timeline,raw}-tab.tsx` へ**移設**（重複実装なし）。`PageHero`（Σ＋「シグマリスの記憶」）はタブ上部に常設し、画面全体の一体感を出した。

## 24. 既存 URL の扱い方・判断根拠

- **`/timeline` → `/memory?tab=timeline` へ恒久リダイレクト**、**`/admin/memory` → `/memory?tab=raw` へ恒久リダイレクト**（各 `page.tsx` を `redirect()` のみに置換）。
- **判断根拠（リダイレクト方式を採用した理由）**: (1) `/memory` を単一の正とすることで「同じ内容が複数URLに散らばる」状態を根本的に解消できる（本タスクの主目的）。(2) 旧URL（ブックマーク・外部リンク・第三段階までのナビ導線）を壊さず、そのまま新画面の該当タブへ導ける。(3) 本文描画は tab コンポーネントへ一元化済みで、リダイレクト側にロジックが残らない（重複ゼロ）。"独立URLのまま同じタブ構造を共有する"案も検討したが、URLの分散が残り主目的に反するため不採用。

## 25. `/chat` サイドバーへの影響・確認結果

- 第三段階で `SigmarisSidebar` に追加した **`/timeline` リンクは廃止**し、記憶関連は **「記憶」(`/memory`) リンク1つへ集約**（`/timeline` は「記憶」の変遷タブに統合されたため）。**`/growth`・`/settings` リンクは維持**。→ サイドバーは 記憶／成長ログ／設定 の3リンク。
- **AppShell ナビも `/timeline` タブを廃止**（`navItems` を5→4項目: chat/記憶/成長ログ/設定）。モバイル下部ナビのグリッドを `grid-cols-5` → `grid-cols-4` に更新。スワイプ遷移は `navItems` を汎用的に辿る実装のため、4項目でも自動的に整合（コード確認）。
- **確認結果**: `/chat` から 記憶（→タブ画面）・成長ログ へ遷移可能。記憶リンク先の `/memory` は現在地タブが既定表示。`/chat` の視覚デザイン・第二段階の常時ダーク保護（`ChatWorkspace` の `.dark`＋`theme="dark"`）は**不変更**。

## 26. テスト結果（第四段階）

| 検証 | 結果 |
|---|---|
| `npx eslint .` | **0 件** |
| `npx next build` | **成功**。`/memory` 動的、`/timeline`・`/admin/memory` は**リダイレクト（静的）**として生成。全ルート健在 |
| `pytest tests/`（backend 16件） | **16 passed**（フロントのみ変更） |
| タブ切替・既存URL・/chat遷移・light/dark | コード上、`?tab=` 遷移／`redirect()`／サイドバー `<Link>`／トークン配色で成立（ビルド・型検査通過）。実ブラウザ目視は未実施（実データ要） |

**差分規模**: 6ファイル −628/+83 行（旧3ページの本文を `components/memory/` の4ファイルへ移設・重複解消）。`/growth` は差分に含まれない（不変更を確認）。

## 27. 変更ファイル一覧（第四段階）

| ファイル | 変更 |
|---|---|
| `frontend/src/app/memory/page.tsx` | シェル＋PageHero＋タブバー＋アクティブタブ本文の描画に再設計 |
| `frontend/src/components/memory/current-tab.tsx` | 新規。「現在地」本文（旧/memory本文＋reflectNow） |
| `frontend/src/components/memory/timeline-tab.tsx` | 新規。「変遷」本文（旧/timeline本文＋EventDecayIndicator） |
| `frontend/src/components/memory/raw-tab.tsx` | 新規。「生データ」本文（旧/admin/memory本文をトークン化＋開発者向け注記） |
| `frontend/src/components/memory/memory-tabs.tsx` | 新規。落ち着いたセグメントのタブバー（client） |
| `frontend/src/app/timeline/page.tsx` | `/memory?tab=timeline` へリダイレクトに置換 |
| `frontend/src/app/admin/memory/page.tsx` | `/memory?tab=raw` へリダイレクトに置換 |
| `frontend/src/components/app-shell.tsx` | navItems から /timeline 削除（5→4）、mobile grid-cols-4 |
| `frontend/src/components/sigmaris-sidebar.tsx` | /timeline リンク削除（記憶へ集約） |

**変更していない（意図的）**: `/growth`（統合対象外）、`/chat` の視覚デザイン・保護、`globals.css`、共有部品、バックエンド。

## 28. 気づいた懸念点・次のステップ（Step 5: Sigmaris Live のサイドバー化）への申し送り

1. **タブ本文はサーバーで該当タブのみフェッチ**する設計。タブ切替は `<Link>`＋サーバーラウンドトリップ（`?tab=`）で、クライアント側の状態保持はしない。体感速度が気になる場合、将来 `prefetch` やクライアントタブ化を検討する余地はあるが、現状は「静かな遷移」を優先した。
2. **`/admin/memory` の隠しページ性**: 旧来は「ナビ非掲載の隠しURL」だったが、統合後は `/memory` の「生データ」タブとして**タブ自体は誰でも見える**ようになった（内容の専門性は注記で明示）。もし"開発者以外の目に触れさせたくない"要件があれば、Step 5 以降でタブの出し分け（例: 環境変数やロールでの表示制御）を検討する余地がある（現状は単一テナントのため実害なしと判断）。
3. **Step 5（Sigmaris Live のサイドバー化）**: `/live` は第三段階で隠しページとして明記済み。Live をチャットのサイドバーへ統合する際は、本段で確立した「`/chat` は常時ダーク・`SigmarisSidebar` のダーク様式でリンク追加」という制約を踏襲すること。また記憶タブと同様、Live も `?` パラメータ or 別サブビューとして落ち着いた切替にすると一貫する。
4. **実ブラウザ目視は未実施**（本環境の制約）。タブ切替・旧URLリダイレクト・`/chat` 遷移・light/dark を本番反映後に実機確認推奨。

---

*第四段階は記憶3ページを `/memory` のタブ（現在地/変遷/生データ）へ統合し、旧URLはリダイレクトで温存、ナビ（AppShell・/chatサイドバー）から重複する /timeline 導線を「記憶」へ集約した。`/growth` は不変更。*
