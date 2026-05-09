import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRightIcon } from "lucide-react";

export const metadata: Metadata = {
  title: "法務情報 | ShiftPilotAI",
  description: "ShiftPilotAIの法務情報、利用規約、プライバシーポリシー、特定商取引法に基づく表記です。",
};

const legalLinks = [
  {
    href: "/legal/tokushoho",
    title: "特定商取引法に基づく表記",
    body: "販売事業者、販売価格、支払方法、解約方法などを掲載しています。",
  },
  {
    href: "/legal/terms",
    title: "利用規約",
    body: "ShiftPilotAIの利用条件、有料プラン、禁止事項、免責事項などを掲載しています。",
  },
  {
    href: "/legal/privacy",
    title: "プライバシーポリシー",
    body: "取得する情報、利用目的、外部サービスへの送信、問い合わせ先などを掲載しています。",
  },
] satisfies Array<{ href: string; title: string; body: string }>;

export default function LegalIndexPage() {
  return (
    <main className="min-h-screen bg-[#f7f2e8] px-4 py-8 text-stone-900 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl">
        <Link
          href="/"
          className="inline-flex rounded-full border border-stone-900/10 bg-white px-4 py-2 text-sm font-semibold text-stone-700 transition hover:bg-stone-50"
        >
          ShiftPilotAIへ戻る
        </Link>

        <section className="mt-8">
          <p className="text-xs font-medium uppercase tracking-[0.28em] text-stone-500">
            Legal
          </p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            法務情報
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-stone-600">
            ShiftPilotAIの利用条件、個人情報の取り扱い、有料プランに関する表示をまとめています。
          </p>

          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {legalLinks.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="group rounded-[24px] border border-stone-900/10 bg-white p-5 shadow-[0_24px_70px_-58px_rgba(41,37,36,0.8)] transition hover:-translate-y-0.5 hover:border-stone-900/20"
              >
                <h2 className="text-lg font-semibold text-stone-950">{item.title}</h2>
                <p className="mt-3 text-sm leading-7 text-stone-600">{item.body}</p>
                <span className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-stone-950">
                  表示する
                  <ArrowRightIcon className="size-4 transition group-hover:translate-x-0.5" />
                </span>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
