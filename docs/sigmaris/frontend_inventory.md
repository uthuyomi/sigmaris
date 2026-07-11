# フロントエンド棚卸し調査

**調査日**: 2026-07-12
**調査範囲**: `frontend/src/app/`配下の全ルート、ナビゲーション構造、認証、未使用コード
**方針**: コード変更は一切行っていない。全て`git log`・実際のソースコードの直接確認に基づく。断定できない箇所は明記した。

---

## 1. 存在する全ルートの一覧と完成度

`frontend/src/app/`配下を`page.tsx`の有無で走査した。**ページとして実際にレンダリングされるルートは13個**（`api/*`のRoute Handlerを除く）。

### 1.1 ページルート（`page.tsx`が存在するもの）

| パス | 目的・役割 | 完成度 | 最終更新 | 最終更新の概要 |
|---|---|---|---|---|
| `/` | ルート。ログイン済みなら`/app`へリダイレクト、未ログインならロゴ+ログインボタンのみの最小画面 | 完成（意図的に最小） | 2026-06-26 | Rebuild frontend as Sigmaris chat app |
| `/app` | `/chat`への即時リダイレクトのみ（中身なし、7行） | 完成（リダイレクト専用） | 2026-06-26 | feat: redesign frontend to chat-based UI with assistant-ui |
| `/login` | ログイン画面。Google認証等の導線、接続ツール紹介 | 完成 | 2026-06-27 | Rename frontend brand to Sigmaris |
| `/launch` | PWA起動時のルーティング用（ログイン済みなら`/chat`、未ログインなら`/login?next=/chat`へリダイレクト） | 完成（リダイレクト専用） | 2026-05-04 | Add PWA install flow with app launch routing |
| `/chat` | **メイン画面。** assistant-ui + ai-sdkによるストリーミングチャット、スレッド管理 | 完成 | 2026-07-03 | Remove the free-chat 20-message limit and Pro upgrade popup from /chat |
| `/memory` | ユーザー向け「記憶」画面。事実記憶・トレンド・自己モデル・ナラティブ章を表示、「今すぐ内省」ボタンあり。ナビゲーション3項目の1つ | 完成 | 2026-06-28 | Implement memory page |
| `/settings` | 設定画面。課金・テーマ・言語・AIトーン・移動手段・Google連携・保存済み場所等、多数のパネルを集約 | 完成 | 2026-06-27 | Rename frontend brand to Sigmaris |
| `/admin/memory` | **開発者専用**の記憶ダッシュボード（B5）。鮮度・矛盾・確信度・出所を一覧表示。コード内コメントで「メインnavには含めない」と明記 | 完成（開発者用画面として） | 2026-07-05 | Phase B5: memory freshness/contradiction dashboard (Phase B complete) |
| `/sigmaris` | **調査で発見した未整理ルート。** 独自の簡易チャットUI（`SigmarisChat`コンポーネント）。詳細は4節参照 | 部分実装/レガシー(推測) | 2026-06-21 | auto-commit |
| `/legal` | 法務情報の目次（特定商取引法・利用規約・プライバシーポリシーへのリンク） | 完成 | 2026-06-27 | Rename frontend brand to Sigmaris |
| `/legal/terms` | 利用規約 | 完成 | 2026-06-27 | Rename frontend brand to Sigmaris |
| `/legal/privacy` | プライバシーポリシー | 完成 | 2026-06-27 | Rename frontend brand to Sigmaris |
| `/legal/tokushoho` | 特定商取引法に基づく表記 | 完成 | 2026-06-27 | Rename frontend brand to Sigmaris |

### 1.2 ディレクトリのみ存在し、`page.tsx`が存在しないもの（ルートとして機能しない）

- `frontend/src/app/calendar/` — 空ディレクトリ。ファイル0件
- `frontend/src/app/timeline/` — 空ディレクトリ。ファイル0件

これらはNext.js App Routerの仕様上、`page.tsx`が存在しない限りルートとして到達不可能。対応する`frontend/src/components/mobility/`・`frontend/src/components/timeline/`も同様に空ディレクトリで、他のファイルからの参照も0件だった（`grep`で確認）。**カレンダー・タイムライン機能のUIは、ディレクトリだけ用意されて未着手のまま**と判断される（実装の痕跡が一切ないため、計画段階で終わったのか、削除し忘れたスキャフォールドなのかは、この調査からは判別できない）。

### 1.3 使用しているバックエンドAPI（主要ページのみ）

| ページ | 呼び出し先 |
|---|---|
| `/chat` | フロントエンドAPI `/api/chat` → バックエンドの**オーケストレーターのストリーミングエンドポイント**（`/api/orchestrator/chat/stream`）。コード内コメント曰く「Phase A1-b」で、直接チャットエンドポイントからオーケストレーター経由へ切り替え済み。記憶注入・スレッド横断セッション継続が有効 |
| `/sigmaris` | フロントエンドAPI `/api/orchestrator/chat`（非ストリーミング）→ バックエンドのオーケストレーター。`/chat`とは別の、より単純な経路 |
| `/memory` | バックエンドの`/api/agent/self/*`系エンドポイントに、エージェント認証ヘッダー（`AGENT_ID`/`AGENT_SECRET`または`AGENT_SECRETS`環境変数）で直接アクセス |
| `/admin/memory` | バックエンドの`/api/app/memory-dashboard`（`readBackendAuthHeaders`経由） |
| `/settings` | Stripe課金（`/api/billing/*`）、Google Calendar/Maps/Sheets設定確認、Supabase設定確認 |

---

## 2. ナビゲーション構造の現状

`frontend/src/components/app-shell.tsx`（`AppShell`コンポーネント）が、ログイン後の全ページで共通利用されるナビゲーションを定義している。ルートレイアウト(`app/layout.tsx`)自体にはナビゲーション要素は一切なく、`TooltipProvider`でラップするのみ。

**ナビゲーションに含まれるのは、以下の3項目のみ**（デスクトップ: 上部タブ、モバイル: 下部固定ナビ、両方とも同一の`navItems`配列を参照）。

1. `/chat`（チャット）
2. `/memory`（記憶）
3. `/settings`（設定）

### 2.1 到達可能性の確認結果

- **`/admin/memory`**: `navItems`に含まれず、他のどのソースファイルからも`href`/リンクとして参照されていない（`grep`で確認）。**URLを直接入力する以外に到達手段がない。** ページ自身のコメントに「Deliberately not part of...the main nav」と明記されており、これは意図的な設計と判断できる。
- **`/sigmaris`**: 同様に`navItems`に含まれず、ページ自身以外からのリンク参照も0件。**到達手段がない。**
- **`/legal`および配下3ページ**: `app/`配下のどのページからもリンクされていない。唯一リンクしているのは`frontend/src/components/landing/landing-page-content.tsx`だが、後述の通りこのコンポーネント自体がどこからも呼ばれていない（4節参照）。**現状、URLを直接入力する以外に到達手段がない。** 法務文書としては通常フッター等に常設リンクを置くのが一般的だが、現状そのような導線は存在しない。
- **`/app`・`/`・`/login`・`/launch`**: いずれもリダイレクト専用または未ログイン時の入口であり、ナビゲーションに含まれる性質のページではない。到達可能性の問題はない。

---

## 3. 認証・権限まわりの確認結果

### 3.1 認証の仕組み

グローバルな`middleware.ts`は**存在しない**（`frontend/src/`・`frontend/`直下を`glob`で確認、ビルド成果物`.next/server/middleware.js`のみ存在するが空のマニフェストであり、ソース上のmiddlewareファイルはない）。認証は各ページのサーバーコンポーネント内で個別に行われている。

- `getCurrentUser()`（`lib/supabase/auth.ts`）: Supabaseセッションからユーザーを取得。未ログインなら`null`。
- `requireUser(nextPath)`: `getCurrentUser()`が`null`の場合、`/login?next=<nextPath>`へリダイレクト。ログイン必須ページはこれを呼んでいる。

`requireUser`を呼んでいるページ: `/chat`・`/memory`・`/settings`・`/admin/memory`・`/sigmaris`。
`getCurrentUser`のみ（未ログインでも閲覧可）: `/`・`/login`・`/launch`。
認証チェックなし（静的): `/legal`・`/legal/terms`・`/legal/privacy`・`/legal/tokushoho`。

### 3.2 権限（ロール）の確認結果

**`requireUser`はログイン済みかどうかのみを見ており、ロール（管理者/一般ユーザー）の区別は一切存在しない。** `/admin/memory`という命名にもかかわらず、内部的には`/chat`や`/settings`と全く同じ`requireUser("/admin/memory")`を呼んでいるだけで、「管理者かどうか」を判定するコードはどこにも見当たらなかった。

本システムは単一テナント（海星さん一人のみが利用者）であるため実害はないと考えられるが、**「開発者専用」という区別は、コード上はナビゲーションから外してあるだけの"隠しページ"であり、認可(authorization)としては何も強制されていない**、という点は正確に記録しておく。`/admin/memory`以外に同種の"開発者専用だが実装上はただの隠しページ"に該当するものは見当たらなかった（`/sigmaris`は開発者専用という位置付けの言及がコード上になく、性質が異なる——4節参照）。

---

## 4. 未使用・古いコードの発見

### 4.1 `/sigmaris`ルート（未整理のレガシー実装と推測）

- 最終更新: 2026-06-21、コミットメッセージ「auto-commit」（自動生成コミットである可能性が高く、意図的な機能追加として書かれた形跡が薄い）
- 内容: `SigmarisChat`という独自コンポーネント（123行）を使った、ストリーミングなし・スレッド永続化なしの簡易チャットUI。`assistant-ui`ライブラリを使わず、`fetch`ベースで`/api/orchestrator/chat`（非ストリーミング）を直接叩く実装
- `/chat`が2026-06-26に「assistant-uiベースのチャット中心UIへの再設計」で作り直された経緯（コミットログ）を踏まえると、**`/sigmaris`は`/chat`が今の形になる前の、より初期のプロトタイプ実装が消し忘れられたものである可能性が高い**（断定はできない。同名の`SigmarisPage`という命名や`requireUser`呼び出しがある点で、コードとして意図的に書かれてはいるが、現行の`/chat`と機能が重複しており、かつ導線が一切ないことから、少なくとも現時点では「使われていない」ことは確実）
- ナビゲーションから到達不可能（2.1節）

### 4.2 ランディングページ関連一式（完全に孤立、未使用と断定できる）

- `frontend/src/components/landing/landing-page-content.tsx`・`frontend/src/components/landing/index.ts`
- `frontend/src/i18n/landing/`配下4ファイル（`copies.ts`・`index.ts`・`locale.ts`・`types.ts`）

これらは相互に参照し合っているだけで、**`frontend/src/app/`配下のどのページ(`page.tsx`)からも一切importされていない**ことを`grep`で確認した。現在のルート`page.tsx`（1節参照）は、ロゴとログインボタンのみの最小画面であり、この`landing-page-content.tsx`（法務ページへのリンク等を含む、より作り込まれたランディングページコンポーネントと推測される）は使われていない。最終更新は2026-06-27（ブランド名変更コミット）で、内容の更新はされているが、呼び出し元が存在しない状態が少なくともその時点から続いていると考えられる。**確実に未使用の孤立コードと判断できる。**

### 4.3 Stripe課金UI（Phase A0の"FREE LIMIT"遺物とは別に、現存する商用SaaS時代の実装）

- `frontend/src/components/billing-panel.tsx`（「シグマリス Pro」プラン表示、Stripe Checkout/Portalへの導線）
- `frontend/src/app/api/billing/checkout/route.ts`・`portal/route.ts`・`status/route.ts`・`webhook/route.ts`
- 最古の関連コミット: 2026-05-08「Add Stripe Pro billing and chat limit」
- 依頼書が言及していた「FREE LIMIT」チャット20メッセージ制限とProアップグレードポップアップは、`grep`で該当文言が見つからず、`/chat`ページの2026-07-03のコミット「Remove the free-chat 20-message limit and Pro upgrade popup from /chat」で**既に除去済み**であることを確認した。
- **しかし、`/settings`ページの`BillingPanel`自体（Stripe Checkout/Portalを開くボタン、Pro/Freeバッジ表示）と、対応するAPIルート4本は、現在も削除されずに残っている。** 本システムが単一テナント（海星さんのみ利用）である現状の設計方針と、この「Pro課金プラン」UIが前提とする複数ユーザー・サブスクリプション課金モデルとの間には、明確な不整合がある。コードが動作するかどうか（Stripe環境変数の設定有無等）はこの調査の範囲外だが、**少なくともUI・API共に削除されず現存している**ことは確認できた。

### 4.4 その他

- `frontend/src/app/calendar/`・`frontend/src/app/timeline/`・対応する`components/mobility/`・`components/timeline/`: 4.1節ではなく1.2節で述べた通り、空ディレクトリ。使われていないというより「まだ何も作られていない」状態。

---

## 5. 全体の一覧表

優先度は「海星さんが個人利用する上で、あった方がよさそうな度合い」を開発者視点で推測したもの（高/中/低/対応不要）。

| パス | 目的・役割 | 完成度 | 優先度の推測 |
|---|---|---|---|
| `/chat` | メインのチャット画面 | 完成 | 対応不要（既に完成・主力機能） |
| `/memory` | 記憶の閲覧・内省トリガー | 完成 | 対応不要（既に完成） |
| `/settings` | 各種設定 | 完成 | 対応不要（既に完成） |
| `/` | ルート（ログイン誘導） | 完成 | 対応不要 |
| `/app` | `/chat`へのリダイレクト | 完成 | 対応不要 |
| `/login` | ログイン画面 | 完成 | 対応不要 |
| `/launch` | PWA起動ルーティング | 完成 | 対応不要 |
| `/admin/memory` | 開発者用記憶ダッシュボード | 完成 | 低〜中（開発・デバッグ時の実用性は高いが、海星さん個人の日常利用には不要。現状維持で問題なし） |
| `/legal`・`/legal/*` | 法務情報 | 完成 | 低（単一テナント個人利用であれば法的な必須度は下がるが、削除するかどこかにリンクを置くかの判断は別途必要） |
| `/sigmaris` | 用途不明の簡易チャット（レガシー疑い） | 部分実装/レガシー(推測) | **要判断**: 実際に使われていないなら削除候補、まだ使う予定があるなら整理が必要 |
| `/calendar`（未実装） | (推測)カレンダー専用ビュー | 未実装(ディレクトリのみ) | 中（現状chatの会話内でしか予定を確認できないため、専用ビューがあれば便利そうだが、優先度は海星さんの実際の要望次第） |
| `/timeline`（未実装） | (推測)タイムライン/日記的なビュー | 未実装(ディレクトリのみ) | 低〜中（直近のTemporal Layer機能と親和性がありそうだが、現時点では推測の域を出ない） |
| ランディングページ一式 | 未ログイン訪問者向け紹介ページ(推測) | 実装済みだが未接続 | 低（単一テナント個人利用のため、訪問者向け紹介ページの必要性自体が低い可能性） |
| Stripe課金UI(`/settings`内) | Pro課金プラン管理 | 完成だが単一テナント方針と不整合 | **要判断**: 単一テナント運用を続けるなら撤去候補 |

---

## 6. 気づいた懸念点・提案（実装はしていません）

1. **`/sigmaris`ルートの扱いを決める必要がある。** 現行の`/chat`と機能が重複し、導線もなく、コミットメッセージも「auto-commit」と情報量が薄い。もし本当に不要であれば削除、まだ何らかの用途（例: オーケストレーターの動作を最小構成で直接デバッグする用の隠し画面、等）があるなら、その旨をコード上に明記しておくことを提案する。

2. **Stripe課金UIと、単一テナント運用方針との不整合。** `docs/persona.md`や本セッションの一連のTemporal Layer作業を踏まえると、本システムは海星さん一人のための個人アシスタントとして運用されている。にもかかわらず`/settings`には「シグマリス Pro」への課金導線が残っており、`/legal/terms`にも有料プランの記載がある。実際にStripeの決済が有効化された状態で運用されているのか、単に削除し忘れているだけなのかは、この調査だけでは判断できない。運用方針を確認した上で、要否を判断することを提案する。

3. **ランディングページ一式（`components/landing/`・`i18n/landing/`）は、孤立コードとして削除候補になりうる。** ただし、将来的に訪問者向けの紹介ページを`/`に再度実装する構想があるなら、雛形として残しておく価値もある。判断材料が本調査だけでは不足しているため、削除は提案するに留め、断定はしない。

4. **`/legal`配下へのリンクが、アプリ内のどこからも到達不可能。** 特定商取引法に基づく表記・利用規約・プライバシーポリシーは、実際にサービスとして運用する上では通常フッター等からの常設導線が期待される文書。現状は意図的に隠されているようには見えず（`/admin/memory`や`/sigmaris`のように「navItemsに入れない」という明確な設計判断のコメントもない）、単に導線を張り忘れている可能性がある。

5. **`/calendar`・`/timeline`が空ディレクトリのまま残っている。** 実装のための一時的なスキャフォールドなのか、構想倒れになったものなのかは判別できない。今後これらのパスを使う計画があるなら着手を、ないなら削除して構造をすっきりさせることを検討してもよいかもしれない。

6. **`/admin/memory`の"開発者専用"は、認可(authorization)としては強制されていない。** 現状は単一テナントのため実害はないが、将来的にマルチユーザー化する可能性が少しでもあるなら、ロールベースのアクセス制御を検討する価値がある（優先度は低いと考えられる — 現状のリスクは実質ゼロ）。
