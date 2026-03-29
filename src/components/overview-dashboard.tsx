import Link from "next/link";
import { scheduleEvents } from "@/lib/mock-schedule";

const cards = [
  {
    title: "チャットで調整",
    text: "OpenAI 連携の会話画面で、予定候補の叩き台をまとめる。",
    href: "/chat",
  },
  {
    title: "カレンダーから日付選択",
    text: "まず日付を決めてから、その日のタイムラインで開始と終了を詰める。",
    href: "/calendar",
  },
  {
    title: "設定を固める",
    text: "Google 連携やデフォルト粒度など、使い勝手に効く項目をここで整える。",
    href: "/settings",
  },
];

export function OverviewDashboard() {
  return (
    <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <section className="rounded-[32px] border border-stone-900/10 bg-white/75 p-5 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
        <p className="text-xs font-medium uppercase tracking-[0.3em] text-stone-500">
          Workflow
        </p>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          {cards.map((card) => (
            <Link
              key={card.href}
              href={card.href}
              className="rounded-[28px] border border-stone-900/10 bg-stone-50 p-4 transition hover:-translate-y-0.5 hover:bg-white"
            >
              <h2 className="text-lg font-semibold text-stone-900">{card.title}</h2>
              <p className="mt-2 text-sm leading-7 text-stone-600">{card.text}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="rounded-[32px] border border-stone-900/10 bg-[linear-gradient(180deg,_rgba(35,31,32,0.96),_rgba(54,48,42,0.92))] p-5 text-stone-50 shadow-[0_30px_90px_-50px_rgba(28,25,23,0.9)]">
        <p className="text-xs uppercase tracking-[0.3em] text-stone-400">Status</p>
        <h2 className="mt-2 text-xl font-semibold">今の状態</h2>
        <ul className="mt-4 space-y-3 text-sm leading-7 text-stone-300">
          <li>チャット UI は OpenAI 連携で動作中</li>
          <li>タイムラインは日付選択後に詳細表示できる</li>
          <li>カレンダーのクリックからその日のタイムラインへ移動できる</li>
          <li>Supabase Auth と Google OAuth の導線を追加済み</li>
        </ul>
        <div className="mt-6 rounded-[24px] bg-white/10 px-4 py-4">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-400">Events</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight">{scheduleEvents.length}</p>
          <p className="mt-1 text-sm text-stone-300">モック予定をプレビューで共有中</p>
        </div>
      </section>
    </div>
  );
}
