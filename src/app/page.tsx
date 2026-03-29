import {
  CalendarDaysIcon,
  Clock3Icon,
  MapPinnedIcon,
  MessageSquareMoreIcon,
} from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/supabase/auth";

export default async function LandingPage() {
  const user = await getCurrentUser();

  if (user) {
    redirect("/app");
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(244,162,97,0.24),_transparent_32%),linear-gradient(180deg,_#f8f5ee_0%,_#efe6d3_52%,_#e7dcc5_100%)] text-stone-900">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex items-center justify-between rounded-[28px] border border-stone-900/10 bg-white/70 px-5 py-4 shadow-[0_20px_60px_-40px_rgba(41,37,36,0.55)] backdrop-blur">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-stone-500">ShiftPilotAI</p>
            <h1 className="mt-1 text-xl font-semibold">Chat-first scheduler</h1>
          </div>
          <Link
            href="/login"
            className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50"
          >
            Login
          </Link>
        </header>

        <section className="grid flex-1 gap-6 py-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-center">
          <div className="rounded-[36px] border border-stone-900/10 bg-white/70 p-6 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur sm:p-8">
            <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Flow</p>
            <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">
              Talk.
              <br />
              Drop files.
              <br />
              Place time.
            </h2>
            <p className="mt-5 max-w-2xl text-sm leading-8 text-stone-600 sm:text-base">
              Chat, calendar, routes, and Google tools in one flow. The UI stays icon-first so the
              schedule is readable before the text gets in the way.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href="/login"
                className="rounded-full bg-stone-900 px-6 py-3 text-sm font-semibold text-stone-50"
              >
                Open app
              </Link>
            </div>
          </div>

          <div className="grid gap-4">
            {[
              { icon: MessageSquareMoreIcon, label: "Chat" },
              { icon: CalendarDaysIcon, label: "Calendar" },
              { icon: Clock3Icon, label: "Timeline" },
              { icon: MapPinnedIcon, label: "Route" },
            ].map((item) => (
              <section
                key={item.label}
                className="rounded-[30px] border border-stone-900/10 bg-white/75 p-6 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur"
              >
                <div className="flex items-center gap-4">
                  <div className="inline-flex size-12 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
                    <item.icon className="size-5" />
                  </div>
                  <h3 className="text-xl font-semibold">{item.label}</h3>
                </div>
              </section>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
