// 役割: 予定や移動情報の概要をダッシュボード表示するReactコンポーネント。

import Link from "next/link";
import {
  overviewCards,
  overviewCopy,
} from "@/components/overview-dashboard-data";
import { scheduleEvents } from "@/lib/mock-schedule";

export function OverviewDashboard() {
  return (
    <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <section className="rounded-[32px] border border-stone-900/10 bg-white/75 p-5 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
        <p className="text-xs font-medium uppercase tracking-[0.3em] text-stone-500">
          {overviewCopy.workflowEyebrow}
        </p>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          {overviewCards.map((card) => (
            <Link
              key={card.href}
              href={card.href}
              className="rounded-[28px] border border-stone-900/10 bg-stone-50 p-4 transition hover:-translate-y-0.5 hover:bg-white"
            >
              <h2 className="text-lg font-semibold text-stone-900">
                {card.title}
              </h2>
              <p className="mt-2 text-sm leading-7 text-stone-600">
                {card.text}
              </p>
            </Link>
          ))}
        </div>
      </section>

      <section className="rounded-[32px] border border-stone-900/10 bg-[linear-gradient(180deg,_rgba(35,31,32,0.96),_rgba(54,48,42,0.92))] p-5 text-stone-50 shadow-[0_30px_90px_-50px_rgba(28,25,23,0.9)]">
        <p className="text-xs uppercase tracking-[0.3em] text-stone-400">
          {overviewCopy.statusEyebrow}
        </p>
        <h2 className="mt-2 text-xl font-semibold">
          {overviewCopy.statusTitle}
        </h2>
        <ul className="mt-4 space-y-3 text-sm leading-7 text-stone-300">
          {overviewCopy.statusItems.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <div className="mt-6 rounded-[24px] bg-white/10 px-4 py-4">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-400">
            {overviewCopy.eventsEyebrow}
          </p>
          <p className="mt-2 text-3xl font-semibold tracking-tight">
            {scheduleEvents.length}
          </p>
          <p className="mt-1 text-sm text-stone-300">
            {overviewCopy.previewing}
          </p>
        </div>
      </section>
    </div>
  );
}
