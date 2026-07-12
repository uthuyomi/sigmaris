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

---

# フロントエンド 不要ページ・レガシーコードの削除・整理（実施報告）

**実施日**: 2026-07-12
**関連**: 上記の棚卸し調査（6章の懸念点1〜3）を受けての削除作業

## 7. 削除した内容の一覧

### 7.1 `/sigmaris`（レガシーな簡易チャットUI）

削除前に、棚卸し調査時点の結果を`grep`で再検証し、`frontend/src/app/sigmaris/page.tsx`自身と`frontend/src/components/sigmaris-chat.tsx`自身を除いて、参照が一切ないことを再確認した上で削除した。

- `frontend/src/app/sigmaris/page.tsx`（ページ本体）
- `frontend/src/components/sigmaris-chat.tsx`（`SigmarisChat`コンポーネント）

**判断根拠として明記する、依頼書の字面を超えた追加削除**: 依頼書は「該当するページ・コンポーネントを削除する」とのみ指示していたが、`sigmaris-chat.tsx`が使っていた以下3ファイルも、削除後に他の利用箇所が一切ないことを確認した上で、あわせて削除した。

- `frontend/src/lib/orchestrator/client.ts`（`sendOrchestratorMessage()`。`sigmaris-chat.tsx`の唯一の呼び出し元）
- `frontend/src/lib/orchestrator/types.ts`（`OrchestratorMessage`型。`client.ts`からのみ参照）
- `frontend/src/app/api/orchestrator/chat/route.ts`（フロントエンドのNext.js APIルート。`client.ts`の`fetch("/api/orchestrator/chat")`からのみ呼ばれていた）

この3ファイルを残すと、`/sigmaris`を消した直後から「呼び出し元が存在しないコード」という、まさに本タスクが解消しようとしている類の孤立コードを新たに生み出すことになるため、削除範囲に含めるのが妥当と判断した。なお、`frontend/src/lib/orchestrator/stream-translator.ts`は`/chat`が使う`frontend/src/app/api/chat/route.ts`から現役で参照されているため、削除していない（`frontend/src/lib/orchestrator/`ディレクトリ自体は残存）。

またWearOSアプリ（`wearos/app/.../MainActivity.kt`）およびPythonスクリプト（`scripts/sigmaris_chat.py`）も`/api/orchestrator/chat`という文言を含むが、いずれも**バックエンドの`/api/orchestrator/chat`エンドポイントを自分のbaseURL設定から直接呼んでおり**、今回削除したフロントエンドのNext.js APIルート（`frontend/src/app/api/orchestrator/chat/route.ts`）は経由していないことをコードで確認済み。これらへの影響はない。

### 7.2 孤立したランディングページ一式

削除前に`grep`で再検証し、以下6ファイルが相互参照のみで、`frontend/src/app/`配下のどのページからもimportされていないことを再確認した上で削除した。

- `frontend/src/components/landing/landing-page-content.tsx`
- `frontend/src/components/landing/index.ts`
- `frontend/src/i18n/landing/copies.ts`
- `frontend/src/i18n/landing/index.ts`
- `frontend/src/i18n/landing/locale.ts`
- `frontend/src/i18n/landing/types.ts`

### 7.3 Stripe課金UI（フロントエンド側のみ）

- `frontend/src/components/billing-panel.tsx`（`BillingPanel`コンポーネント本体）
- `frontend/src/components/settings/index.ts`から`export * from "@/components/billing-panel";`の1行を削除（バレルファイルの更新のみ、他のエクスポートは無変更）
- `frontend/src/app/settings/page.tsx`から`BillingPanel`の import・JSX呼び出し・`readBillingStatus(user.id, user.email)`の呼び出しと`billing`変数を削除（他のパネル・機能には一切手を加えていない）
- `frontend/src/app/api/billing/checkout/route.ts`
- `frontend/src/app/api/billing/portal/route.ts`
- `frontend/src/app/api/billing/status/route.ts`
- `frontend/src/app/api/billing/webhook/route.ts`（Stripeからの受信Webhookエンドポイント。フロントエンド内部からの呼び出し元は元々存在しなかった——Stripe側の設定でこのURLへのWebhook送信が現在も有効になっている場合、削除後は404になる点に注意。Stripeダッシュボード側の設定変更要否はこの調査・実装の範囲外のため、8節に運用者向けの確認事項として記載する）

## 8. Stripe関連で、バックエンド・関連コードに残したものとその理由

以下は**意図的に削除していない**。依頼書の指示（バックエンドのテーブル・関連コードに触れないこと、`/legal`に一切触れないこと）に基づく判断。

- **`frontend/src/lib/billing.ts`（`readBillingStatus`・`isProBillingStatus`等）**: 削除していない。理由は2つある。(1) `frontend/src/lib/billing-gate.ts`の`requireProPlan()`が、Google Calendar同期(`/api/sync/google-calendar`)・データインポート(`/api/import/preview`・`/api/import/commit`)・移動予定スケジュール(`/api/mobility/schedule`)・プッシュ通知購読(`/api/import/subscribe`)という**現役で使われている4つのAPIルートの機能ゲート**として、この関数を直接呼び出している（HTTP経由ではなく関数呼び出し）。依頼書が削除対象として明示したのは`/settings`のProパネルと`/api/billing/*`の4ルートのみであり、これらのゲート機能自体は削除対象に含まれていない。誤って削除すると、この4機能に予期しない影響（型エラーによるビルド不能、またはゲート判定不能によるランタイムエラー）が及ぶため、意図的に残した。(2) これは今回削除した`/api/billing/*`（Stripeの決済・ポータル・受信Webhook）とは異なる、Pro/Free判定という**読み取り専用の判定ロジック**であり、依頼書が指す「Stripe課金UI」（決済導線そのもの）には該当しないと判断した。
- **`frontend/src/lib/billing-gate.ts`**: 上記と同じ理由で残した。中身は一切変更していない。
- **`frontend/src/lib/stripe.ts`**（`PRO_MONTHLY_PRICE_JPY`・`getStripe`・`getProPriceId`・`hasStripeConfig`）: 削除していない。`frontend/src/app/legal/terms/page.tsx`と`frontend/src/app/legal/tokushoho/page.tsx`が`PRO_MONTHLY_PRICE_JPY`を直接importしており、削除すると`/legal`のビルドが壊れる。依頼書が「`/legal`には一切触れないこと」と明示している以上、このファイルは全体を残す以外の選択肢がないと判断した。**`getStripe`・`getProPriceId`・`hasStripeConfig`は、`/api/billing/*`削除後は呼び出し元がなくなり、この3つの関数自体は未使用コードとして残っている**（`PRO_MONTHLY_PRICE_JPY`のみ現役）。同一ファイル内の一部エクスポートだけを削除する編集は、`/legal`が依存するファイルに手を入れることになり「一切触れない」という制約と衝突するリスクがあると判断し、ファイル全体を無変更のまま残すことを選んだ。これは判断根拠として明記する——もし`/legal`の内容自体を見直すタイミングが来れば、その時に合わせてこの3関数の要否も再検討するのが安全だと考える。
- **バックエンドの`billing_customers`・`subscriptions`等のテーブル・関連するPythonコード**: 一切調査・変更していない（依頼書の指示通り、フロントエンドのUI・APIルートのみを対象とした）。

## 9. テスト結果

### 9.1 ビルド・Lint

```
cd frontend && rm -rf .next && npx next build
```

初回ビルドは`.next/dev/types/validator.ts`という**過去のビルドキャッシュが生成した、削除済み`/sigmaris`ルートを参照する型検証ファイル**の残存によりTypeScriptエラーで失敗した。これはソースコードではなくビルド成果物（`.next/`、gitignore対象）であり、`.next`ディレクトリを削除してクリーンビルドし直したところ、型エラーは解消し、正常にビルドが完了した。

```
✓ Compiled successfully in 11.7s
  Running TypeScript ...
  Finished TypeScript in 10.3s ...
✓ Generating static pages using 15 workers (39/39)
```

ビルド出力のルート一覧（`Route (app)`）を確認し、`/sigmaris`・`/api/orchestrator/chat`・`/api/billing/*`が一覧から消え、`/chat`・`/memory`・`/settings`・`/admin/memory`・`/login`・`/legal`とその配下3ページを含む他の全ルートが引き続き存在することを確認した。

```
cd frontend && npx eslint .
```

警告・エラーとも0件（出力なし）。

### 9.2 コードベース全体の参照チェック

`grep`で以下のパターンをフロントエンド全体（`frontend/src`配下）に対して検索し、**削除対象への参照が一切残っていないことを確認した**（マッチ0件）。

```
sigmaris-chat|SigmarisChat|components/landing|i18n/landing|BillingPanel|billing-panel|api/billing|lib/orchestrator/client|lib/orchestrator/types|app/sigmaris
```

`frontend`全体（`.ts`/`.tsx`/`.json`/`.mjs`/`.js`、大文字小文字無視）に対しても`sigmaris|landing|billing`で広く再検索し、ヒットした29ファイルを個別に目視確認した。全て「Sigmaris」というブランド名としての言及、または本タスクで意図的に残した`lib/billing.ts`・`lib/billing-gate.ts`・`lib/stripe.ts`・`/legal`関連であり、削除対象への参照は含まれていなかった。

### 9.3 既存テスト

```
cd backend && ./.venv/Scripts/python.exe -m pytest tests/ -q
16 passed in 1.60s
```

本タスクはフロントエンドのみが対象のため、バックエンドの既存テストへの影響はそもそもない（実際に影響なしを確認済み）。フロントエンド側には元々テストスイートが存在しないため（`package.json`の`scripts`は`dev`/`build`/`start`/`lint`のみ）、9.1節のビルド成功とLintのクリーンさを、フロントエンドの検証結果として位置づけている。

### 9.4 要件との対応

1. `/sigmaris`削除、`/chat`機能への影響なし: ビルド成功・`/chat`のルート出力に変化なし・`sendOrchestratorMessage`等の削除ファイルへの参照0件で確認済み
2. 孤立ランディングページの削除: 完了、参照0件で確認済み
3. Stripe課金UI(フロントエンド側)削除・バックエンドテーブル保持: フロントエンドのコンポーネント・APIルートのみ削除、バックエンドは未調査・未変更
4. `/legal`に一切手を加えていないこと: `frontend/src/app/legal/`配下は今回のdiffに一切含まれていない（`git status`で確認）
5. 既存主要ページへの悪影響なし: ビルド成功、ルート一覧に`/chat`・`/memory`・`/settings`・`/admin/memory`・`/login`が全て残存

## 10. 気づいた懸念点

1. **Stripe Webhookの受信設定（Stripeダッシュボード側）が、今回のコード削除と同期していない可能性がある。** `/api/billing/webhook`を削除したため、もしStripe側の設定でこのアプリのURLへWebhookを送信する設定が現在も有効なら、今後そのリクエストは404になる。実際にStripeでの決済が有効化された状態で運用されているかは、この調査・実装だけでは判断できないため、運用者側での確認を推奨する。
2. **`lib/stripe.ts`の`getStripe`・`getProPriceId`・`hasStripeConfig`が未使用のまま残っている。** 8節で述べた通り、`/legal`に触れないという制約を優先した結果の意図的な残置であり、今すぐの実害はない。`/legal`の内容を将来見直す際に、あわせて整理を検討する価値がある。
3. **今回の削除は棚卸し調査で発見した3点（`/sigmaris`・ランディングページ・Stripe UI）に限定しており、`/calendar`・`/timeline`の空ディレクトリ、および`requireProPlan`で機能ゲートされている4つのAPIルート（Google Calendar同期・データインポート・移動予定・プッシュ通知購読）については、依頼書の明示的な指示通り一切手を加えていない。** これらのAPIルートは、海星さんのアカウントのbilling状態（`billing_customers`/`subscriptions`テーブル）次第では、実際には現在も402エラーでブロックされている可能性がある——これは今回の変更が原因ではなく、Stripe課金機能の削除前から存在していた状態であり、本タスクのスコープ外として触れていない。単一テナント運用の実態に照らして、これらのゲート自体の要否を見直すかどうかは、別タスクとしての検討価値がある。

---

# `/timeline`ページの実装（実施報告）

**実施日**: 2026-07-12
**関連**: Temporal Layer Step1〜3（`docs/sigmaris/temporal_layer_report.md`）の成果を可視化するページ

## 11. 採用したグラフ・可視化ライブラリとその選定理由

**Recharts(v3系)を新規に採用した。**

判断根拠:

- 導入前の調査で、`frontend/package.json`にグラフ・可視化ライブラリは一切導入されていないことを確認した（Recharts・Tremorいずれも未導入）。既存のUIは`shadcn`(CLI)・`radix-ui`・`tailwind-merge`・Tailwind v4という、プリミティブなコンポーネントを自前でTailwindスタイリングする構成(`frontend/src/components/ui/`に`avatar`・`button`・`collapsible`・`dialog`・`tooltip`の5つのみ)であることを確認した。
- **Tremorは不採用とした。** Tremorは自身の配色・余白・カード等のデザイン言語をある程度前提としたコンポーネント群であり、依頼書が最優先事項として明示した「既存の`/chat`のデザインシステムを踏襲すること」「新規に大きく異なるデザイン言語を持ち込まないこと」という制約と相性が悪いと判断した。
- **Rechartsを採用した。** SVGベースの薄いプリミティブ(`BarChart`・`Bar`・`XAxis`等)を組み合わせる設計で、独自のデザイン言語を持ち込まず、既存の`/memory`・`/admin/memory`が確立している配色トークン(背景`#212121`/`#2a2a2a`、アクセント`#9b59b6`、ミュートテキスト`#8e8ea0`等)をそのまま`fill`・`stroke`・`contentStyle`等のprops経由で適用できる。shadcn/uiの公式レシピ集(`shadcn/ui`のchartコンポーネント)もRechartsを標準の組み合わせ先としており、将来shadcnのchart系コンポーネントを追加導入する際の親和性も高い。
- React 19・Next.js 16との互換性を`npm install`実行後の`package.json`(`"recharts": "^3.9.2"`)およびビルド成功で確認済み。

用途は「出来事(event)」セクションの**週次件数の棒グラフ1つ**に限定した。state/traitセクションや個々のevent項目のTTL進捗表示は、既存の`/memory`ページの`ConfidenceBar`と同じ、素のTailwindによる進捗バー(`<div style={{width: ...}}>`)で実装している——グラフライブラリが必要なのは「複数時点にまたがる集計」を見せる場面に限られると判断し、単一の値を示すインジケーターにまでRechartsを持ち込むことは、依頼書の「新規に大きく異なるデザイン言語を持ち込まないこと」という制約に照らして過剰と考えた。

## 12. 表示する情報の設計

`/memory`ページと同じ`AppShell`・カード・配色トークンを踏襲した3セクション構成。

### event(出来事)

- 新しい順の時系列リスト。各カードに`category/key`・内容・生成日時(バッジ)を表示
- **TTL(90日)の進捗インジケーター**: 生成からの経過日数を進捗バーで表示し、「あと{N}日で自然に薄れる目安」または(90日超過時)「自然減衰の目安を超えています」という文言を添える。**判断根拠**: B17の実際の減衰計算(`_EVENT_DECAY_RULE`の90日/0.5という減衰係数、importance_scoreによる調整等、`memory_validator.py`)をフロントエンドで再現するのではなく、依頼書が明示した「生成から90日でTTLの対象になることが分かるように」という要件に沿った、単純な経過日数の可視化にとどめた。実際の確信度減衰カーブとこの表示が数値的に一致するとは限らない、という点は明示しておく。
- **週次件数の棒グラフ**(Recharts): 直近13週(91日)を週次バケットに分けて件数を表示。13週とした理由は、12週(84日)だとTTLの目安(90日)にわずかに届かず、TTL間際のeventがグラフの範囲外に出てしまうため——実装中にテストで発見し、13週に調整した(14節参照)。

### state(状態)

- 現在有効な状態(`superseded_by is null`)を`category/key`ごとに一覧表示
- **supersededされた過去の状態の履歴**: 依頼書がA3のsupersede/superseded_byパターンを参照するよう指示していた通り、`(category, key)`でグルーピングし、`valid_from`(なければ`created_at`)昇順に並べたときの末尾を「アクティブな行」、それ以外を「履歴」として扱う設計にした。**判断根拠**: supersede/superseded_byは常に同一`(category, key)`内でのみ発生する(`upsert_fact_item` RPCの分岐ロジック、Temporal Layer Step1で確認済み)という前提に基づく単純化であり、`superseded_by`のIDを辿って厳密にチェーンを再構成しているわけではない。通常の運用ではこの前提が崩れることはないはずだが、万一データ不整合があった場合は表示が不正確になりうる、という制約として明記する。
- 履歴は、既存のshadcn/uiプリミティブである`Collapsible`(`frontend/src/components/ui/collapsible.tsx`、既に導入済みで未使用だったコンポーネント)を使い、「過去の履歴を見る({N}件)」というトリガーで折りたたみ表示にした。デフォルトで閉じておくことで、通常表示は「現在の状態一覧」に集中できるようにしている。

### trait(傾向)

- **B14の判断傾向**(`sigmaris_user_preference_patterns`): `pattern_statement`と、根拠となった判断の件数(`evidence_count`)、最終確認日時を表示。
- **memory_kind='trait'の事実記憶**(`user_fact_items`): `category/key`・内容と、`/memory`ページと同じ`ConfidenceBar`コンポーネントで実際のconfidence値を表示。

**判断根拠(traitの二重表示について)**: 依頼書は「trait(傾向): B14が抽出した判断傾向を、確信度とともに表示する」と指示していたが、調査の結果`sigmaris_user_preference_patterns`テーブル(`202607100032_user_preference_patterns.sql`)には`confidence`列が存在せず、あるのは`evidence_count`(根拠となった判断の件数)のみだった。これを「confidence」と称して表示すると実態と異なるデータを確信度として提示することになるため、**B14のpatternは「根拠件数」として明示的に区別して表示し**、Temporal Layer Step1の移動コメント(「trait: 判断傾向・好み...B14が既にこの概念を所有している」)が示唆する通り、実際にconfidence値を持つ`memory_kind='trait'`の`user_fact_items`行を別枠で並べて表示する、という2ソース構成にした。これにより依頼書の「確信度とともに表示する」という要件は、少なくとも一方のデータソースで文字通り満たされている。

### B5(`/admin/memory`)との役割分担

13節で詳述。

## 13. 追加したバックエンドAPI

### 13.1 既存APIの確認結果(追加不要と判断した部分)

`/admin/memory`が使う`/api/app/memory-dashboard`(`backend/app/routes/app_data.py`)は`_DASHBOARD_SELECT`という限定的な列セット(`memory_kind`・`valid_from`・`superseded_by`・`last_mentioned_at`を含まない)しか返さないため、これは`/timeline`の情報源として使えないことを確認した。

一方、`/memory`ページが既に使っている`/api/agent/facts/items`(`backend/app/routes/agent.py`)は、内部で`get_fact_items(jwt, category=category)`を呼んでおり、`active_only`引数を渡していない(デフォルト`False`)ため、**`FACT_ITEM_SELECT`の全列(`memory_kind`・`valid_from`・`superseded_by`・`last_mentioned_at`を含む)を、`is_deleted`/`is_stale`/`superseded_by`によるフィルタなしで返す**ことをコードで確認した。これはStep1〜3のTemporal Layer実装が`FACT_ITEM_SELECT`にこれらの列を追加した際、この既存エンドポイント自体は変更していなかったため、意図せず(しかし都合よく)`/timeline`が必要とする全情報を既に返せる状態になっていた。**したがって、event/stateセクションについては新規のバックエンドAPI追加は不要と判断した**(依頼書2節の「不足していれば追加する」の"不足していない"側のケース)。

### 13.2 新規追加したAPI

`sigmaris_user_preference_patterns`(B14の判断傾向)を読み取る既存の`/api/agent/*`エンドポイントは存在しなかったため、以下を新規追加した。

```
GET /api/agent/preference-patterns/list
```

`backend/app/routes/agent.py`に、既存の`/trends/list`と全く同じ形(`_verify_agent`→`_require_jwt`→サービス関数呼び出し→`{"ok": True, "patterns": [...], "count": N}`)で実装した。内部では既存の`decision_log.py::get_active_preference_patterns(limit=50)`をそのまま呼んでいる(新規のサービス関数は書いていない、既存関数の再利用)。

**判断根拠(jwt検証について)**: `get_active_preference_patterns()`は`sigmaris_user_preference_patterns`テーブルがservice_role専用RLS(`202607100032_user_preference_patterns.sql`)であるため、内部でサービスロールキーを使ってアクセスしており、渡された`jwt`自体は使っていない。それでも`_require_jwt(authorization)`の呼び出しは残した——この router の他の全エンドポイントが認証ヘッダーを必須にしている一貫性を優先し、将来ユーザースコープの絞り込みが必要になった場合の変更コストを下げるための判断。

## 14. B5(`/admin/memory`)との役割分担の実装上の違い

| 観点 | B5(`/admin/memory`) | `/timeline` |
|---|---|---|
| データ取得 | `/api/app/memory-dashboard`(限定列、`is_deleted=false`のみでフィルタ) | `/api/agent/facts/items`(全列、フィルタなし) + 新規`/api/agent/preference-patterns/list` |
| 表示単位 | `user_fact_items`の生データをテーブル形式でそのまま一覧 | `memory_kind`(event/state/trait)という**Temporal Layerの分類軸**で再構成 |
| 「変遷」の見せ方 | 個々の行の`updated_at`・`is_stale`フラグを列として並べるのみ | eventは週次グラフ+TTL進捗バー、stateはsupersedeチェーンの折りたたみ履歴、という**変化そのものを主役にした見せ方** |
| ナビゲーション | 意図的にnavItemsから除外(コード内コメントで明記済み、既存) | navItemsに追加(4つ目のタブ) — 一般利用を想定 |
| トーン | 開発者向けダッシュボード然としたテーブルUI(既存のまま変更なし) | `/memory`・`/chat`と統一感のあるカード・バッジ・進捗バーのUI |
| 対象読者 | 開発者(海星さん自身が開発者としてデバッグする用途) | 海星さんが利用者として眺める用途 |

コード面では、両ページとも最終的に同じ`user_fact_items`テーブルを読んでいる(B5は`get_memory_dashboard_items()`経由、`/timeline`は`get_fact_items()`経由)ため、データソースの二重管理にはなっていない——依頼書が要求した「役割分担」は、取得する列の粒度と、取得後の再構成・見せ方の違いとして実装した。

## 15. フロントエンド実装の詳細

- **`frontend/src/lib/backend/agent-client.ts`(新規、共有モジュール)**: `/memory`ページが個別に実装していた`readAgentHeaders()`・`fetchAgentJson()`を切り出した。`/timeline`でも同じ`/api/agent/*`呼び出しパターンが必要になったため、3箇所目の重複を避ける目的の純粋なリファクタリング(挙動は変更していない)。`/memory/page.tsx`はこの共有モジュールを使うよう更新し、ビルド・Lintで回帰がないことを確認した。
- **`frontend/src/lib/timeline/transform.ts`(新規)**: event/state/traitへの分類、supersedeチェーンの構築、TTL経過日数計算等の**フレームワーク非依存の純粋関数群**をページ本体から切り出した。理由は2つ: (1) フロントエンドにテストランナー(Jest/Vitest等)が導入されていないため、React/Next.jsに依存しない純粋関数として切り出すことで、追加の依存ライブラリなしに`npx tsx`で直接テストできるようにするため(16節参照)、(2) データ整形とプレゼンテーションの関心分離。
- **`frontend/src/components/timeline/event-volume-chart.tsx`(新規、クライアントコンポーネント)**: Rechartsの`BarChart`をラップ。
- **`frontend/src/components/timeline/state-history-disclosure.tsx`(新規、クライアントコンポーネント)**: 既存の`Collapsible`プリミティブを使った履歴の折りたたみ表示。
- **`frontend/src/app/timeline/page.tsx`(新規)**: サーバーコンポーネント。`requireUser("/timeline")`でログイン必須、`/memory`・`/settings`と同じ`AppShell`+ダーク配色トークンを使用。
- **`frontend/src/components/app-shell.tsx`(更新)**: `navItems`に`/timeline`(ラベル「タイムライン」、アイコン`HistoryIcon`)を追加。モバイル下部ナビの`grid-cols-3`を`grid-cols-4`に変更(3項目決め打ちだったグリッドを4項目対応に修正)。

## 16. テスト結果

### 16.1 サンプルデータによる純粋関数の検証

フロントエンドにテストランナーが未導入のため、`frontend/src/lib/timeline/transform.ts`の純粋関数を対象に、`npx tsx`で直接実行できるスクラッチテストを作成した(実行時のみ`frontend/`直下に一時配置し、検証後に削除——リポジトリには一切コミットしていない)。event 3件(直近・TTL内・TTL超過)・state 2系列(1系列はsupersede履歴あり)・trait 2件(confidence付き)・is_deletedの行1件、というサンプルデータで以下を検証した。

- event/state/traitへの分類が正しく行われること、`is_deleted`行が除外されること
- eventが新しい順に並ぶこと、traitがconfidence降順に並ぶこと
- **supersededされた過去の状態(state)が、履歴として正しく抽出されること**(要件3の直接検証): 2段階supersedeされた系列で、アクティブな行(最新)と履歴(1件、過去の値)が正しく分離されることを確認
- 履歴のないstate系列では、履歴が空配列になること
- TTL(90日)内/超過それぞれのケースで、経過日数計算が正しいこと
- 週次件数グラフのバケット数・集計件数が正しいこと(この検証中に、12週だとTTL目安に届かない不整合を発見し、13週に修正——後述)
- 各種フォーマッタ(不正な日付文字列でも例外を投げない等)・confidenceのクランプ処理・patternのソート順

```
15 passed, 0 failed
```

### 16.2 ビルド・Lint

```
cd frontend && rm -rf .next && npx next build
```

```
✓ Compiled successfully in 19.4s
  Running TypeScript ...
  Finished TypeScript in 17.0s ...
✓ Generating static pages using 15 workers (40/40)
```

ビルド出力のルート一覧に`/timeline`が追加され、`/chat`・`/memory`・`/settings`・`/admin/memory`・`/login`・`/legal`とその配下を含む既存の全ルートが引き続き存在することを確認した。

```
cd frontend && npx eslint .
```

警告・エラーとも0件。

### 16.3 バックエンド

新規追加した`/api/agent/preference-patterns/list`について、`_verify_agent`・`_require_jwt`・`get_active_preference_patterns`をモックしたスクラッチテストを2件作成し、正常系(patternsが返る)・空配列(patternsが0件でもエラーにならない)を確認した。

```
2 passed
```

既存の`backend/tests/`(16件)も全て再実行し、リグレッションは確認されなかった。

```
16 passed in 0.76s
```

### 16.4 実モデル・実データでの確認について

実際のSupabase認証・本番相当のバックエンドAPIを介した目視確認(ブラウザでの実際のレンダリング)は行っていない。依頼書の注意事項通り、追加のサーバーアクセス・APIキー取得は試みていない。16.1節のサンプルデータ検証は、ページ本体から切り出した純粋なデータ整形ロジックに対するものであり、実際のAPIレスポンス形式(バックエンドの`FACT_ITEM_SELECT`が返す実際のJSON)との整合は、型定義(`FactItem`型)を`user_fact_data.py`の`FACT_ITEM_SELECT`列一覧と手動で突き合わせる形でのみ確認している。**運用者側で確認すべきこと**: 実際にログインした状態で`/timeline`にアクセスし、(1) event/state/traitそれぞれのセクションに実データが表示されること、(2) supersedeされたstateの履歴が実際に折りたたみ表示されること、(3) モバイル下部ナビの4項目表示が崩れていないこと、を目視確認することを推奨する。

### 16.5 要件との対応

1. event/state/traitが時系列で表示されること: 実装済み、サンプルデータで検証済み
2. `/chat`のデザインシステムとの統一感: `/memory`・`/admin/memory`と同じ`AppShell`・配色トークン・カードスタイルを踏襲(新規に持ち込んだのはRechartsのグラフ描画のみで、色は既存トークンをそのまま適用)
3. supersededされた過去の状態を履歴として確認できること: 実装済み、サンプルデータで検証済み(16.1節)
4. ナビゲーションから到達できること: `AppShell`の`navItems`に追加済み
5. 既存機能への悪影響: ビルド成功・Lint成功・既存ルート一覧に変化なし・バックエンド既存テスト16件成功

## 17. 気づいた懸念点

1. **13節で述べた通り、`/api/agent/facts/items`は`active_only`フィルタなしで全件(is_deleted含む)を返す設計になっている。** `/timeline`側でクライアントサイドに`is_deleted`のフィルタを実装して対応したが、このエンドポイントの本来の呼び出し元である`/memory`ページも同じ「全件取得」を行っており、そちらは`is_deleted`のフィルタを行っていない(今回の調査で気づいたが、`/memory`ページ自体の修正はスコープ外のため触れていない)。削除済みの事実記憶が`/memory`ページに表示され続けている可能性があり、次の`/memory`ページ改修の際に確認する価値がある。
2. **stateのsupersedeチェーン構築は`(category, key)`グルーピング+時系列ソートという単純化した前提に基づいている(12節)。** `superseded_by`のIDを厳密に辿ってグラフ構造として再構成しているわけではないため、万一データ不整合(同一`category`/`key`で複数のアクティブな行が存在する等、本来UNIQUE制約で起こり得ないはずの状態)があった場合、表示が実態と食い違う可能性がある。
3. **traitセクションのB14 pattern表示は「根拠件数(evidence_count)」であり、依頼書が言う「確信度」そのものではない(12節)。** `sigmaris_user_preference_patterns`にconfidence列を追加する設計変更は本タスクのスコープ外と判断し、実施していない。
4. **event種別のTTL進捗表示は、B17の実際の減衰計算式(`memory_validator.py`の`_EVENT_DECAY_RULE`、importance_scoreによる調整)を再現したものではなく、単純な経過日数/90日の可視化にとどめている(12節)。** 表示上の「あと{N}日」という数字と、実際にB17がconfidenceを減衰させ始めるタイミングは、厳密には一致しない場合がある。
5. **`/api/agent/preference-patterns/list`は新規のjwt必須エンドポイントとして追加したが、実際にはservice-role専用テーブルを読むだけでjwtの中身は使っていない(13.2節)。** 依頼書の「既存のパターンに沿った実装とすること」を優先してこの一貫性のない状態を許容したが、将来的にはこのrouter全体の認証設計(jwtが実際に必要なエンドポイントとそうでないエンドポイントが混在している)を見直す価値があるかもしれない。
