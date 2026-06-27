import type { Metadata } from "next";
import Link from "next/link";
import { PRO_MONTHLY_PRICE_JPY } from "@/lib/stripe";

export const metadata: Metadata = {
  title: "利用規約 | シグマリス",
  description: "シグマリスの利用規約です。",
};

const sections = [
  {
    title: "第1条（適用）",
    body: "本規約は、シグマリス（以下「本サービス」といいます）の利用条件を定めるものです。ユーザーは、本サービスを利用することにより、本規約に同意したものとみなされます。",
  },
  {
    title: "第2条（サービス内容）",
    body: "本サービスは、AIチャットによる予定管理支援、Google Calendar連携、勤務表・画像・スプレッドシートからの予定抽出、移動時間の計算、出発前通知などを提供します。AIによる提案や抽出結果は完全性・正確性を保証するものではなく、ユーザーは内容を確認したうえで利用するものとします。",
  },
  {
    title: "第3条（アカウント）",
    body: "ユーザーは、Google OAuth等の認証手段を用いて本サービスにログインします。アカウントの管理はユーザーの責任で行うものとし、第三者による不正利用が判明した場合は速やかに運営者へ連絡するものとします。",
  },
  {
    title: "第4条（有料プラン）",
    body: `シグマリス Proは月額${PRO_MONTHLY_PRICE_JPY.toLocaleString("ja-JP")}円（税込）のサブスクリプションです。支払いはStripeを通じて行われ、決済完了後にPro機能を利用できます。`,
  },
  {
    title: "第5条（解約）",
    body: "ユーザーは、アプリ内の設定画面からStripeの請求管理画面へ進み、いつでも有料プランを解約できます。解約後も、契約期間の終了まではPro機能を利用できます。",
  },
  {
    title: "第6条（返金）",
    body: "デジタルサービスの性質上、決済完了後の返金には原則として応じられません。ただし、法令上必要な場合または運営者が個別に認めた場合はこの限りではありません。",
  },
  {
    title: "第7条（禁止事項）",
    body: "ユーザーは、不正アクセス、過度な負荷を与える行為、第三者の権利を侵害する行為、法令または公序良俗に反する行為、本サービスの運営を妨害する行為を行ってはなりません。",
  },
  {
    title: "第8条（外部サービス）",
    body: "本サービスは、Google、Stripe、Supabase、OpenAI等の外部サービスと連携します。外部サービスの仕様変更、停止、障害等により本サービスの一部機能が利用できない場合があります。",
  },
  {
    title: "第9条（免責）",
    body: "運営者は、本サービスの利用により生じた損害について、運営者の故意または重大な過失がある場合を除き、責任を負いません。予定登録、通知、移動時間計算等は補助機能であり、最終的な確認はユーザーの責任で行うものとします。",
  },
  {
    title: "第10条（規約の変更）",
    body: "運営者は、必要に応じて本規約を変更できます。変更後の規約は、本サービス上に掲載した時点で効力を生じます。",
  },
] satisfies Array<{ title: string; body: string }>;

export default function TermsPage() {
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
            Terms
          </p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            利用規約
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
