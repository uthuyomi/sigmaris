# フロントエンド棚卸し 2026（デザイン統一・共通ナビゲーション新設に向けて）

**調査日**: 2026-07-21
**性質**: 調査・提案のみ。**本タスクではコードの実装・デザインの変更を一切行っていない。**
**対象コミット**: `427f627`（main）
**方針**: `frontend/src/app/` 配下の各ページ・主要コンポーネントの**実ソースを開いて**確認した。ファイル名からの推測はしていない。
**既存の `docs/sigmaris/frontend_inventory.md`（2026-07-12）は過去の記録としてそのまま残す。** 本ドキュメントはその後の変化（`/timeline`・`/growth`・`/live` の追加、ナビゲーションの3→5項目化等）を反映した最新版である。

---

## 0. 依頼書の前提に対する重要な訂正（先に述べる）

依頼書は「**どのページからも他のページへ移動できる共通のナビゲーションが存在しない**」を前提としているが、実ソースを確認した結果、これは**現状と部分的に異なる**。正確には次の通り（コード上の事実）:

- `frontend/src/components/app-shell.tsx` の `AppShell` は、**5項目の共通ナビゲーション**（`/chat`・`/memory`・`/timeline`・`/growth`・`/settings`）を、デスクトップ上部タブ＋モバイル下部固定ナビ＋左右スワイプで提供している。`/memory`・`/timeline`・`/growth`・`/settings`・`/admin/memory` はこの `AppShell` を使う＝**これら相互の行き来は既に可能**。
- ただし、**共通化が破綻している箇所が3つ**ある。これが依頼書の問題意識の実体である:
  1. **`/chat` はナビゲーションを意図的に外している。** `/chat` は `<AppShell ... fitViewport>` で描画され、`fitViewport` 分岐は共通ヘッダー・下部ナビを**一切描画しない**（`app-shell.tsx` の該当分岐）。`/chat` の唯一の移動手段は独自の `SigmarisSidebar`（`/memory`・`/settings` へのリンクのみ）で、**`/chat` から `/timeline`・`/growth`・`/live` へは行けない。**
  2. **`/live` はナビゲーションも被リンクも存在しない完全な孤立ページ。** `AppShell` を使わず独自 `<main>` で描画。`frontend/src` 全体を検索しても `/live` への `Link`/`href` は**自分自身の `requireUser("/live")` 以外に0件**（URL直打ちのみ到達可能）。
  3. **`/admin/memory` はナビ項目に無い。** `AppShell` で描画されるため「そのページからは5項目ナビが見える」が、**どこからも `/admin/memory` へリンクされていない**（開発者用の隠しページ、意図的）。

つまり課題は「共通ナビが**無い**」ではなく、「**共通ナビ（AppShell）と、`/chat` 独自サイドバーという2系統が併存**し、`/live` が孤立し、`/chat` から一部ページへ到達できない」こと。デザインも「バラバラ」ではなく「**3系統のスタイル手法が併存**」している（§4）。

---

## 1. 全ページ一覧

`frontend/src/app/` 配下で `page.tsx` を持つルートは **15個**（`api/*` の Route Handler を除く）。

| パス | シェル | デザインの特徴（実クラスから判断） | 利用状況（被リンク） | 機能概要 | 主な依存コンポーネント |
|---|---|---|---|---|---|
| `/` | なし（独自） | 最小画面。ロゴ＋ログイン | 入口（リダイレクト元） | 未ログイン時ロゴ＋ログイン、ログイン済は`/app`へ | — |
| `/app` | なし | 中身なし | 入口 | `/chat` へ即リダイレクト | — |
| `/launch` | なし | 中身なし | PWA入口 | ログイン状態で `/chat` or `/login?next=/chat` | — |
| `/login` | なし（独自） | ログイン専用レイアウト | 入口 | Googleログイン、接続ツール紹介 | `auth-controls` |
| `/chat` | **`AppShell fitViewport`（＝ナビ非表示）** | **独自ダークシェル** `bg-[#212121]`＋サイドバー`bg-[#171717]`、アクセント`#9b59b6`。ChatGPT風フルハイト | AppShellナビの`/chat`タブ、`/`等からの誘導 | メインのストリーミングチャット、スレッド管理 | `ChatWorkspace`, `SigmarisSidebar`, `Assistant`(assistant-ui), `thread`, `markdown-text`, `tool-fallback`, `ui/*` |
| `/memory` | `AppShell`（フル） | **ハードコード hex ダーク**（`bg-[#212121]`/`bg-[#2a2a2a]`/`bg-[#2f2f2f]`/`text-[#ececec]`/`text-[#8e8ea0]`/`bg-[#9b59b6]`）。カード＋Σヘッダー | AppShellナビ＋`SigmarisSidebar`から | 事実記憶・傾向・自己モデル・自己物語、「今すぐ自己反省」 | `AppShell`, `agent-client`（**Section/Badge/ConfidenceBar等はページ内でインライン定義**） |
| `/timeline` | `AppShell`（フル） | `/memory` とほぼ同一の hex ダークカード。Rechartsの棒グラフ追加 | AppShellナビ | Temporal Layer可視化（event/state/trait、supersede履歴、TTL進捗、週次件数グラフ） | `AppShell`, `timeline/event-volume-chart`(Recharts), `timeline/state-history-disclosure`, `ui/collapsible`, `lib/timeline/transform` |
| `/growth` | `AppShell`（フル） | `/memory`/`/timeline` と同一の hex ダークカード。Rechartsの折れ線 | AppShellナビ | 内部健全性（RC-5・Grounding・Drive State・承認待ち・Safety Governance） | `AppShell`, `growth/trend-line-chart`(Recharts), `lib/growth/transform` |
| `/live` | **なし（独自`<main>`）** | `/growth` の hex ダークをコピー流用。**ただしAppShellなし＝ナビ無し** | **被リンク0件（孤立）** | 内部処理のリアルタイムSSE可視化。`?demo=1`で架空データ再生 | `live/live-dashboard`＋`live/*`（`use-live-events`, `use-mock-live-events`, `demo-scenarios`, `live-metrics`, `live-event-log`, `live-process-flow`, `live-event-detail-panel`） |
| `/settings` | `AppShell`（フル） | **stone/light系クラス＋`.settings-page`ダーク補正**（globals.css）。他ページと別手法 | AppShellナビ＋`SigmarisSidebar`から | テーマ/言語/AIトーン/移動手段/到着リード/Google同期/保存済み場所/連携状態 | `AppShell`, `settings/*`（各Panel） |
| `/admin/memory` | `AppShell`（フル） | AppShell＋テーブルUI（開発者向け） | **被リンク0件（ナビ非掲載・意図的）** | 記憶の鮮度・矛盾・確信度・出所を生データでテーブル表示（B5） | `AppShell`, `memory-dashboard-table` |
| `/legal` | なし（独自） | 静的 | 被リンク0件（アプリ内導線なし） | 法務目次 | — |
| `/legal/terms` | なし | 静的 | 同上 | 利用規約（`PRO_MONTHLY_PRICE_JPY` を参照） | `lib/stripe`（定数のみ） |
| `/legal/privacy` | なし | 静的 | 同上 | プライバシーポリシー | — |
| `/legal/tokushoho` | なし | 静的 | 同上 | 特定商取引法表記（`PRO_MONTHLY_PRICE_JPY` 参照） | `lib/stripe`（定数のみ） |

### 1.1 過去の棚卸し（2026-07-12）からの差分
- **削除済みが確実に消えている**（残存なし）: `/sigmaris`（レガシーチャット）、ランディングページ一式（`components/landing/`・`i18n/landing/`）、Stripe課金UI（`billing-panel.tsx`・`/api/billing/*`）、空ディレクトリ `/calendar`。→ 前回クリーンアップの「消し忘れ」は無い。
- **新規追加**: `/timeline`（旧・空スキャフォールドを実装）、`/growth`（Phase Vis）、`/live`（Sigmaris Live）。
- **ナビゲーション拡張**: `navItems` が旧3項目（chat/memory/settings）→ **5項目**（chat/memory/timeline/growth/settings）へ。モバイル下部ナビも `grid-cols-3`→`grid-cols-5`。左右スワイプ遷移も追加。

---

## 2. 「必要・不要」の仕分け提案（判断根拠つき）

判断は「海星さん一人の個人利用」という単一テナント前提。**最終判断は開発者に委ねる**。

| パス | 提案 | 判断根拠 |
|---|---|---|
| `/chat` | **今後も必要** | 主力機能。ただしナビ統合の対象（§3・§5） |
| `/memory` | **今後も必要** | 記憶の閲覧＋自己反省トリガー。中核 |
| `/settings` | **今後も必要** | 設定集約 |
| `/`・`/app`・`/launch`・`/login` | **今後も必要** | 認証・入口・リダイレクト専用。統合不可 |
| `/timeline` | **必要（ただし /memory・/admin/memory と役割整理）** | データ源が `user_fact_items` で `/memory`・`/admin/memory` と重複。見せ方（時間軸再構成）で差別化しているが、"記憶を見る"目的が3ページに分散 |
| `/admin/memory` | **統合を検討** | `/timeline`・`/memory` と同じ `user_fact_items` の別ビュー（生データのテーブル）。開発者用。`/timeline` の「開発者/生データ」タブへ吸収する余地。現状維持でも実害はない（隠しページ） |
| `/growth` | **必要（役割は明確に別）** | データが記憶ではなく"シグマリス自身の健全性"（RC/Drive/承認待ち）。目的は他と重ならない。デモ・発信素材としても価値。ただしナビ上は"見る系"に同居 |
| `/live` | **要判断（統合 or 明示的な隠しページ化）** | 孤立（被リンク0）。価値はデモ/X発信（`?demo=1`）と内部処理の可視化。恒久機能なら**ナビへ正式導線**を、デモ専用なら`/admin/memory`同様「意図的な隠しページ」とコメント明記を推奨。現状は"中途半端に孤立"している |
| `/legal`・`/legal/*` | **必要（ただし導線を張るか判断）** | 文書として必要だが、アプリ内のどこからもリンクされていない。フッター等の常設導線を張るか、単一テナントで不要と判断するかは別途 |

### 2.1 「記憶・状態を見る」ページの重複（依頼書が特に懸念した点）
`/memory`・`/timeline`・`/admin/memory`・`/growth`・`/live` の**目的の重なり**を整理:

| ページ | 何を見るか | データ源 | 対象読者 |
|---|---|---|---|
| `/memory` | 事実・傾向・自己モデル・物語（現在地） | `/api/agent/{facts,trends,self,narrative}` | 利用者 |
| `/timeline` | 記憶の**時間変遷**（event/state/trait） | `/api/agent/facts/items` ＋ preference-patterns | 利用者 |
| `/admin/memory` | 記憶の**生データ**（鮮度・矛盾） | `/api/app/memory-dashboard` | 開発者 |
| `/growth` | シグマリス自身の**健全性** | `/api/agent/growth/*` | 利用者/開発者 |
| `/live` | 内部処理の**リアルタイム** | `/api/agent/live/*`（SSE） | 利用者/デモ |

→ `/memory`・`/timeline`・`/admin/memory` は**同じ記憶を別角度で見る3ページ**であり、統合または明確なタブ化の第一候補。`/growth`・`/live` は"記憶"ではないため統合はせず、**役割を明示**した上で共通ナビに正しく載せるのが妥当（提案は §5）。

---

## 3. ナビゲーションの現状

**2系統が併存**している（コード上の事実）。

### 3.1 AppShell ナビ（`app-shell.tsx`）
- `navItems` = **5項目**: `/chat`・`/memory`・`/timeline`・`/growth`・`/settings`（`dict.nav` ＋ 直書きラベル「記憶/タイムライン/成長ログ」の混在）。
- デスクトップ: ヘッダー右の丸角アイコンタブ（`lg:` で表示）。モバイル: 下部固定ナビ（`grid-cols-5`）。加えて**左右スワイプ**で `navItems` 順に遷移（`navigateBySwipe`）。
- これを描画するのは `/memory`・`/timeline`・`/growth`・`/settings`・`/admin/memory`。

### 3.2 `/chat` 独自サイドバー（`SigmarisSidebar`）
- `/chat` は `AppShell fitViewport` で描画され、**AppShellのヘッダー・下部ナビは出ない**（`fitViewport` 分岐が `children` のみ描画）。
- 代わりに `SigmarisSidebar`（`bg-[#171717]`）が、スレッド履歴＋新規チャット＋**下部リンク`/memory`・`/settings`の2つのみ**を提供。`/timeline`・`/growth`・`/live` へのリンクは無い。

### 3.3 到達不能・非対称の実態（実grep）
- **`/live`**: `frontend/src` 全体で `/live` への `Link`/`href` は**0件**（自ページの `requireUser("/live")` のみ）。URL直打ち限定。
- **`/admin/memory`**: `navItems` に無く、被リンク0件（意図的な隠しページ）。
- **`/chat` → `/timeline`・`/growth`・`/live`**: 到達手段なし（サイドバーに項目が無い）。
- **`/legal/*`**: アプリ内被リンク0件。
- 逆に AppShellページ相互（memory/timeline/growth/settings/chat）は5項目ナビで相互到達可能。

**結論**: 「共通ナビが無い」のではなく、「AppShellの5項目ナビ」と「chatのサイドバー2リンク」が分断され、`/live` が孤立、`/admin/memory` が隠れている、という**非対称・二重化**が現状の問題。

---

## 4. デザインシステムの現状比較（`/chat` と他ページ）

実ソースのクラス記述を突き合わせた結果、**3つのスタイル手法が併存**している。

### 4.1 基盤トークン（`globals.css`）— 実は「ダーク単一」
- `html`/`body` は `background:#212121; color:#ececec; color-scheme:dark`（**ダーク固定**）。
- shadcn風CSS変数: `--background:#212121`・`--card:#2f2f2f`・`--primary:#9b59b6`・`--muted-foreground:#8e8ea0`・`--sidebar:#171717`。**`:root` と `.dark` の値は完全に同一**＝実質ダークオンリー設計。
- 加えて、AppShellが使う light 系クラスをダークへ**再マップする補正**が `@layer components` にある（例: `.dark [class*="bg-white/"] { background-color: rgb(47 47 47/.95) }`、`.settings-page` 専用の色補正群）。

### 4.2 手法A: shadcn CSS変数ベース（`/chat`）
- `/chat`・`SigmarisSidebar`・assistant-ui は、`--background`/`--card`/`--primary`/`--sidebar` 等のトークンや素の hex（`#212121`/`#171717`/`#9b59b6`/`#ececec`/`#8e8ea0`）を使用。
- レイアウトはフルハイトのChatGPT型（サイドバー＋会話ペイン）。`chat-thread-surface` 等の専用CSSあり。
- **依存**: `ui/*`（shadcnプリミティブ: button/dialog/tooltip/collapsible/avatar）、assistant-ui。

### 4.3 手法B: AppShellの light-first インライン（`AppShell` chrome ＋ `/settings`）
- `AppShell` の外枠は **light前提**: `bg-[#f7f7f8] text-stone-950 dark:bg-[#212121] dark:text-stone-100`、ヘッダー `bg-white ... dark:bg-[#2f2f2f]`、ナビpill `bg-stone-100 dark:bg-white/8`。テーマは `document.documentElement.classList.toggle("dark", theme==="dark")` で切替。
- `/settings` はパネル側も stone/light 系クラスを使い、`.settings-page` のダーク補正（globals.css）に依存。
- → **light/dark両対応を意図した唯一の系統**だが、他ページ本文（手法C）とはトーンが異なる。

### 4.4 手法C: 本文のハードコード hex ダーク（`/memory`・`/timeline`・`/growth`・`/live`）
- 本文は `bg-[#212121]`（コンテナ）・`bg-[#2a2a2a]`（Section）・`bg-[#2f2f2f]`（ヘッダーカード）・`bg-[#212121]`（アイテムカード）・`text-[#ececec]`・`text-[#8e8ea0]`・`bg-[#9b59b6]`（進捗/アクセント）・`#e07856`（注意色）を**arbitrary値で直書き**。
- **CSS変数（`bg-background`/`bg-card`/`text-muted-foreground`/`bg-primary`）を使っていない**＝§4.1のトークンをバイパス。
- **テーマ非対応**: これらの本文 `div` は `theme` propに関係なく常に `#212121` ダーク。→ **light テーマ時、AppShellのchrome（白系ヘッダー/stoneナビ）と本文（`#212121`ダーク）が食い違う**という不整合が生じる（コード上の帰結）。

### 4.5 コンポーネントの重複（統一の最大の障害）
`/memory`・`/timeline`・`/growth` は、`Section`・`Badge`・`ConfidenceBar`・`EmptyState`・`ErrorState`・`Σ`ヘッダーカードを**各 `page.tsx` 内でインライン再定義**している（共有コンポーネント化されていない）。`/live` も同様のカードを独自に持つ。**同じ見た目のコピー実装が4ファイルに分散**しており、デザイン統一時はまずここの共通化が必要。

### 4.6 差分まとめ（`/chat` を基準に）
| 観点 | `/chat` | `/memory`・`/timeline`・`/growth` | `/live` | `/settings` |
|---|---|---|---|---|
| シェル | `AppShell fitViewport`（ナビ非表示）＋独自サイドバー | `AppShell`（5項目ナビ） | なし | `AppShell` |
| 色の指定方法 | CSS変数＋hex | **hex直書き**（トークン不使用） | hex直書き | stone/light＋`.settings-page`補正 |
| テーマ対応 | ダーク固定 | 本文はダーク固定（chromeのみ切替） | ダーク固定 | light/dark両対応 |
| 共有UI | `ui/*`（shadcn） | 各ページでインライン再定義（重複） | 独自 | `settings/*`パネル |
| グラフ | なし | Recharts（timeline/growth） | 独自（live-*） | なし |

---

## 5. 今後の「デザイン統一・ナビゲーション新設」に向けた次ステップ提案（実装はしない）

優先度つきの手順案。**いずれも提案であり、着手は開発者判断。**

### 5.1 デザイントークンの一本化（最初にやるべき土台）
- §4.4の**hex直書きを、`globals.css` の意味トークン（`bg-background`/`bg-card`/`bg-primary`/`text-muted-foreground` 等）へ置換**する方針を決める。既に `--card:#2f2f2f` 等が同値で定義済みのため、見た目を変えずに置換できる余地が大きい。
- `/chat` の色は既にトークン寄り。**`/chat` のダーク系を"正"のデザイン言語**とし、AppShellの light-first（手法B）を「ダーク固定へ寄せる」か「light/darkを全ページで正しく効かせる」かを**先に決める**（現状の"chromeだけlight対応/本文はダーク固定"の食い違いを解消）。

### 5.2 共有UIコンポーネントの抽出
- `/memory`・`/timeline`・`/growth`（・`/live`）に重複する `Section`/`Card`/`Badge`/`ConfidenceBar`/`EmptyState`/`ErrorState`/`Σヘッダー` を、`components/ui/` または `components/dashboard/` に**共有コンポーネントとして切り出す**。これがデザイン統一の実体になる。

### 5.3 共通ナビゲーションの一本化
- **`/chat` を含めた統一ナビ**を設計する。現状 `/chat` は `fitViewport` でナビを消しているため、(a) `/chat` にも共通ナビ（サイドバー内 or 上部）から `/timeline`・`/growth` へ行ける導線を足す、(b) AppShellのナビと `SigmarisSidebar` の**役割を決める**（例: サイドバー＝会話履歴専用、ページ間移動＝共通ナビに集約）。
- **`/live` をナビに正式追加するか、隠しページと明記するか**を決める（現状は孤立）。追加する場合、`navItems` の項目数変更＝モバイル下部ナビのグリッド（現`grid-cols-5`）と、`/live` 自身のAppShell化が必要（`live/page.tsx` のコメントが「今は見送った」と明記している通り、これは全ページ影響の変更）。
- **`/admin/memory`** は開発者用として隠したままにするか、`/timeline` の「生データ」タブへ統合するかを決める。

### 5.4 "記憶・状態を見る"ページの役割整理（§2.1）
- `/memory`（現在地）・`/timeline`（時間変遷）・`/admin/memory`（生データ）を、**1つのタブ化された「記憶」画面**へ集約する案を検討。`/growth`（自己健全性）・`/live`（内部処理）は"記憶"と別軸なので、ナビ上で**「記憶」「状態/内部」**のようにグルーピングすると混乱が減る。

### 5.5 付随的な導線
- `/legal/*` への常設導線（フッター等）を張るか、単一テナントで不要と判断するかを決める。

### 5.6 進め方の順序（推奨）
1. §5.1 トークン方針の確定（light/dark をどうするか） → 2. §5.2 共有UI抽出 → 3. §5.3 ナビ一本化（`/chat`・`/live` を含む）→ 4. §5.4 役割整理・タブ化。
- **1→2 を先に済ませると、3以降で各ページの見た目を触らずナビだけ再設計できる**ため手戻りが少ない。

---

## 6. 調査に使った証拠（主なファイル）
- ナビ: `frontend/src/components/app-shell.tsx`（`navItems` 5項目・`fitViewport` 分岐・スワイプ）、`frontend/src/components/sigmaris-sidebar.tsx`（`/memory`・`/settings` のみリンク）
- ページ本体: `frontend/src/app/{chat,memory,timeline,growth,live,settings}/page.tsx`、`frontend/src/app/admin/memory/page.tsx`、`frontend/src/components/chat-workspace.tsx`
- デザイン基盤: `frontend/src/app/globals.css`（トークン・ダーク固定・`.settings-page`補正・swipe/drawerアニメーション）
- 到達性: `grep` で `/live`・`AppShell`・`href` 参照を確認（`/live` 被リンク0件、AppShell利用7ファイル）
- ページ一覧: `git ls-files frontend/src/app | grep page.tsx`（15ページ、`/calendar` は消滅済み）
- **実ブラウザでのレンダリング目視は未実施**（フロントに自動テストが無く、本タスクは静的調査のため）。light テーマ時の chrome/本文の食い違い（§4.4）は、実機で確認する価値がある。

---

*本ドキュメントは読み取り専用の調査成果物であり、コード・デザインのいずれにも変更を加えていない。既存の `frontend_inventory.md` にも手を加えていない。*
