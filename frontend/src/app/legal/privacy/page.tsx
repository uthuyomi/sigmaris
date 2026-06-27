import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "プライバシーポリシー | シグマリス",
  description: "シグマリスのプライバシーポリシーです。",
};

const sections = [
  {
    title: "1. 取得する情報",
    body: "本サービスは、ログインに必要なメールアドレス、ユーザーID、サービス利用に伴い入力された予定情報、設定情報、Google Calendar連携に必要な認可情報、チャット内容、アップロードされた画像やファイルの内容、決済状態を確認するためのStripe顧客ID・サブスクリプションID等を取得する場合があります。",
  },
  {
    title: "2. 利用目的",
    body: "取得した情報は、本人認証、予定管理機能の提供、Google Calendar連携、AIによる予定抽出・応答生成、移動時間計算、出発前通知、有料プランの課金管理、問い合わせ対応、サービス改善、不正利用防止のために利用します。",
  },
  {
    title: "3. 決済情報",
    body: "クレジットカード番号等の決済情報はStripeが管理し、本サービスのサーバーでは保存しません。本サービスは、課金状態の確認に必要なStripe顧客ID、サブスクリプションID、決済ステータス等のみを保存します。",
  },
  {
    title: "4. 外部サービスへの送信",
    body: "本サービスは、機能提供のためにGoogle、Stripe、Supabase、OpenAI、Vercel等の外部サービスを利用します。入力内容や連携データは、必要な範囲でこれらのサービスに送信される場合があります。",
  },
  {
    title: "5. 第三者提供",
    body: "運営者は、法令に基づく場合を除き、ユーザーの同意なく個人情報を第三者に提供しません。",
  },
  {
    title: "6. 安全管理",
    body: "運営者は、環境変数による秘密情報管理、アクセス制御、Supabase RLS、Webhook署名検証等により、取得した情報の漏えい、滅失、改ざん等を防止するために必要な安全管理措置を講じます。",
  },
  {
    title: "7. 開示・訂正・削除",
    body: "ユーザーは、法令に基づき、自己の個人情報について開示、訂正、削除、利用停止等を求めることができます。希望する場合は、本ポリシー記載の連絡先までご連絡ください。",
  },
  {
    title: "8. お問い合わせ",
    body: "本ポリシーに関するお問い合わせは、kaiseif4e@gmail.com までご連絡ください。",
  },
  {
    title: "9. 改定",
    body: "運営者は、必要に応じて本ポリシーを改定します。改定後の内容は、本サービス上に掲載した時点で効力を生じます。",
  },
] satisfies Array<{ title: string; body: string }>;

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-[#f7f2e8] px-4 py-8 text-stone-900 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-4xl">
        <Link
          href="/"
          className="inline-flex rounded-full border border-stone-900/10 bg-white px-4 py-2 text-sm font-semibold text-stone-700 transition hover:bg-stone-50"
        >
          シグマリスへ戻る
        </Link>

        <section className="mt-8 rounded-[28px] border border-stone-900/10 bg-white p-5 shadow-[0_30px_80px_-60px_rgba(41,37,36,0.75)] sm:p-8">
          <p className="text-xs font-medium uppercase tracking-[0.28em] text-stone-500">
            Privacy Policy
          </p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            プライバシーポリシー
          </h1>
          <p className="mt-4 text-sm leading-7 text-stone-600">
            制定日: 2026年5月9日
          </p>

          <div className="mt-8 space-y-6">
            {sections.map((section) => (
              <section key={section.title}>
                <h2 className="text-base font-semibold text-stone-950">{section.title}</h2>
                <p className="mt-2 text-sm leading-7 text-stone-600">{section.body}</p>
              </section>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
