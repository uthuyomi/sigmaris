# インシデント対応報告: 無料チャット上限(FREE LIMIT)制限の削除

**背景:** `/chat`に「無料チャット上限20回に達しました」「シグマリスProが月額980円」という課金・利用制限ポップアップが表示され、メッセージが送信できなくなる状態が発生した。このリポジトリの前身(ShiftPilotAI・AdFlow AI寄りのSaaS開発時期)に実装された無料プラン利用回数制限が、個人利用のシグマリスに転用された後もそのまま残存していたもの。
**作業ブランチ:** `phase-free-limit-removal`(`main`から新規作成)
**方針:** 制限を「回避」ではなく「削除」する。ただし、将来のSaaS化を見据えた課金基盤(Stripe連携・`billing_customers`/`subscriptions`テーブル・他機能のPro限定ゲート)は無関係な範囲として一切削除しない。

---

## 1. 削除した箇所の一覧

### フロントエンド(実際に送信をブロックしていた経路)

| ファイル | 変更内容 |
|---|---|
| `frontend/src/app/api/chat/route.ts` | `/chat`のメッセージ送信APIルート。`readBillingStatus`/`readChatUsageStatus`を呼び、Pro未加入かつ`usage.limited`の場合に`createUpgradeStream()`(「無料チャット上限に達しました」というメッセージをストリームとして返し、実際のオーケストレーターへは一切転送しない)を返していたブロックを削除。**これが実際にメッセージ送信をブロックしていた唯一のサーバーサイド判定。** |
| `frontend/src/lib/chat-usage.ts` | **ファイルごと削除。** `readChatUsageStatus()`・`FREE_CHAT_MESSAGE_LIMIT`(=20)は、この無料チャット上限機能のためだけに存在しており、他に呼び出し元が無いことを確認済み(2章参照)。 |
| `frontend/src/app/chat/page.tsx` | `billing`/`chatUsage`の取得(`readBillingStatus`・`readChatUsageStatus`)と、`<ChatWorkspace>`への`freeChatUsage`プロップ受け渡しを削除。 |
| `frontend/src/components/chat-workspace.tsx` | `freeChatUsage`プロップの型定義・受け取り・`<Assistant>`への受け渡しを削除。 |
| `frontend/src/app/assistant.tsx` | `freeChatUsage`プロップ、および専らその計算にしか使われていなかった`initialUserMessageCount`の算出・`<Thread>`への受け渡しを削除。 |
| `frontend/src/components/thread.tsx` | `ThreadProps`から`freeChatUsage`/`initialUserMessageCount`を削除。上限到達判定(`usedChatCount`/`chatLimitReached`/`remainingChatCount`)の算出ロジックを削除。上限到達時のバナーコンポーネント`ChatLimitNotice`(「無料チャット上限」「シグマリスPro」「Proプランを見る」ボタンを含む)を削除。`<Composer>`に渡していた`disabled={chatLimitReached}`(送信欄・添付ボタン・送信ボタンを無効化していた唯一の条件)を削除し、`Composer`の`disabled`プロップ自体を廃止(この用途以外に使われていなかったため)。 |

### バックエンド

**バックエンド(FastAPI)側には、チャット回数をカウント・制限する仕組みは一切存在しなかった。** `backend/app/services/chat.py`・`orchestrator/service.py`を確認したが、メッセージ件数に基づく送信ブロックのロジックは見つからなかった。無料チャット上限は完全にNext.js側(フロントエンドのBFF層、`/api/chat` route.ts)だけで実装されていたため、バックエンドの変更は不要だった。

---

## 2. 課金関連テーブル・コードの扱い(判断根拠)

**`billing_customers`・`subscriptions`テーブル、および関連コードは一切削除・変更していない。** チャット送信をブロックしていた判定ロジックの部分のみを削除した(要件4の保守的な選択肢をそのまま採用)。

### 調査結果: これらは今回のチャット制限以外の用途で広く使われている

`@/lib/billing`(`readBillingStatus`・`isProBillingStatus`)・`@/lib/stripe`(`PRO_MONTHLY_PRICE_JPY`ほか)の実際の呼び出し元を横断的に調査したところ、以下が見つかった。いずれも今回のチャット無料枠とは別の、独立した機能。

| 箇所 | 用途 |
|---|---|
| `frontend/src/lib/billing-gate.ts` | チャット以外の複数のAPIルート(Google Calendar同期・push通知購読・移動時間スケジュール・インポートpreview/commit等、計6箇所以上)で使われている一般的な機能ゲート機構。 |
| `frontend/src/app/settings/page.tsx` + `billing-panel.tsx` | Settings画面のサブスクリプション管理UI(「Proプランを利用中です」「支払いを管理」)。チャット画面とは別の、契約管理そのもの。 |
| `frontend/src/app/api/billing/{checkout,portal,webhook,status}/route.ts` | Stripeの決済・ポータル・Webhook・現在の契約状態取得。 |
| `frontend/src/app/legal/{terms,tokushoho}/page.tsx` | 特定商取引法・利用規約ページ内の価格表示。 |
| `frontend/src/components/landing/landing-page-content.tsx` | 公開マーケティングページのPro機能訴求。**このページ自体は今回のタスクの対象範囲(「チャット画面」)には含まれないと判断し、変更していない。** 実際に外部提供されているかは別途確認が必要だが、機能的にチャット送信をブロックしているものではなく、単なる静的な紹介文言のため、無関係な削除巻き込みを避けた。 |
| `backend/app/services/chat_tools.py`(`has_pro_plan`) | チャット内の**特定のツール**(`PRO_ONLY_TOOLS`、例: Google Calendar書き込み系)をPro未加入時に使わせない、ツール単位のゲート。**今回報告された「20回で送信自体がブロックされる」現象とは別の仕組みであり、そもそもメッセージの送受信自体は妨げない。** 対象外として変更していない。 |

### `billing_customers`テーブルについて

`billing_customers`という名前のテーブルは`supabase/migrations/202605080013_billing_subscriptions.sql`で作成されており、Stripeの顧客ID紐付けに`api/billing/{checkout,portal,webhook}`から使われている。**今回のチャット無料枠機能(`chat-usage.ts`・`chat/route.ts`)はこのテーブルを直接参照していなかった**(`subscriptions`テーブルのみ参照)。テーブル自体・関連マイグレーション・Stripe連携コードは一切触れていない。

**結論**: 削除対象は「チャットメッセージ数を数えて送信をブロックする」というロジック(`chat-usage.ts`全体、および`chat/route.ts`のブロック分岐)のみに限定した。課金基盤そのもの(テーブル・Stripe連携・Settings画面・他機能のPro限定ゲート)は将来のSaaS化やPro限定ツールの運用に必要な可能性があるため、要件4の指示通り保守的に温存した。

---

## 3. 他の経路(WearOS等)への同様の制限の有無

調査の結果、**`/chat`(`Assistant`/`Thread`コンポーネント経由)以外の経路には、この制限は元々一切存在しなかった。**

- **`/sigmaris`**(`SigmarisChat`コンポーネント): `freeChatUsage`・`chat-usage`・`billing`関連の参照は無し。また送信先も`/api/chat`ではなく`/api/orchestrator/chat`という別のNext.js APIルートであり(`lib/orchestrator/client.ts`経由)、そちらにも同様のブロック処理は存在しない。**元から無関係。**
- **WearOS**: Kotlinアプリからバックエンド(FastAPI)へ直接リクエストしており、Next.jsの`/api/chat`層自体を経由しない。上記の通りバックエンド側にはそもそも制限が存在しないため、**元から無関係。**

したがって、追加で削除すべき箇所は見つからなかった。

---

## 4. テスト結果

### コードレベルでの確認(要件1・2)

- `frontend/src/lib/chat-usage.ts`を削除し、`FREE_CHAT_MESSAGE_LIMIT`・`readChatUsageStatus`・`ChatUsageStatus`への参照がリポジトリ内に一切残っていないことを`grep`で確認した(0件)。
- `chatLimitReached`・`freeChatUsage`・`ChatLimitNotice`・`PRO_MONTHLY_PRICE_JPY`(thread.tsx内)・`isProBillingStatus`/`readBillingStatus`(route.ts・chat/page.tsx内)への参照も同様に0件であることを確認した。
- `<Composer>`は`disabled`プロップを完全に廃止し、送信欄・添付ボタン・送信ボタンを無条件で有効な状態にした(`ComposerPrimitive.Input`/`ComposerPrimitive.AddAttachment`の`disabled`属性を削除)。送信ボタン自体は入力が空のときのみ無効化される(`canSend = composerText.trim().length > 0`、上限判定を含まない元々の入力バリデーションのみ)。

**実際に20往復送信して確認する実機テストは行っていない。** 指示書の「手間であればコードレベルの確認でも可」という許容に従い、上記のコード確認とビルド・型検査で代替した。ブロック分岐そのもの(`if (!isProBillingStatus(billing) && usage.limited)`)がファイルから物理的に消えているため、何回送信しても発生しようがない状態になっている。

### ビルド・型検査

```
npx tsc --noEmit          -> エラー0件
npx eslint <変更5ファイル>  -> エラー・警告0件
npm run build              -> ✓ Compiled successfully, 44ページ生成成功
```

`/chat`ルート(`ƒ /chat`)を含む全ルートが正常にビルドされることを確認した。

### 既存テスト

`backend/tests/`(既存8件)全てPASS、`import app.main`成功(バックエンドは今回無変更のため、既存動作に影響がないことの確認)。

---

## 5. 気づいた懸念点

1. **`landing-page-content.tsx`(公開マーケティングページ)には依然として「無料枠を超えても」「チャット上限解除」という、今回削除した制限の存在を前提にした文言が残っている。** 今回のタスクは明示的に「チャット画面」に対象を限定していたため触れていないが、この制限自体が無くなった以上、このページの文言は実態と矛盾している。対外公開されているページであれば、内容の見直しが必要と考えられる(判断材料が必要なため、別タスクとして扱うことを推奨)。
2. **`billing-panel.tsx`・Settings画面のPro管理UI・Stripe連携(`/api/billing/*`)は今回一切手を付けていないが、実際に外部への課金提供を行っていないのであれば、これらも将来的に整理対象になりうる。** 今回は「将来必要になりうる基盤は残す」という保守的な指示に従い判断を保留した。
3. **`chat_tools.py::has_pro_plan`によるツール単位のPro限定ゲートは今回のタスクの対象外としたが、これも「対外課金プラン運用を行っていない」という現状の運用方針と整合しているか、別途確認が必要かもしれない。** 具体的にどのツールが`PRO_ONLY_TOOLS`に指定されているか未確認のため、影響有無の判断は今回行っていない。

---

## Related Documents

- [phase_a1b_report.md](phase_a1b_report.md) — `/chat`が実際に使われるチャットUIであることを確認した経緯
