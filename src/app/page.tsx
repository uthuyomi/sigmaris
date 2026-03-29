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
            <h1 className="mt-1 text-xl font-semibold">チャットで組む予定調整アプリ</h1>
          </div>
          <Link
            href="/login"
            className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50"
          >
            ログインへ
          </Link>
        </header>

        <section className="grid flex-1 gap-6 py-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-center">
          <div className="rounded-[36px] border border-stone-900/10 bg-white/70 p-6 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur sm:p-8">
            <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Landing</p>
            <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">
              日付、時間、移動まで
              <br />
              ひとつの流れで詰める
            </h2>
            <p className="mt-5 max-w-2xl text-sm leading-8 text-stone-600 sm:text-base">
              ShiftPilotAI は、チャットで予定候補を作り、カレンダーで日付を決めて、
              タイムラインで開始と終了を詰めるためのアプリだよ。Google Calendar、
              Google Sheets、Google Maps とつないで、予定と移動をまとめて扱える。
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href="/login"
                className="rounded-full bg-stone-900 px-6 py-3 text-sm font-semibold text-stone-50"
              >
                ログインして始める
              </Link>
              <Link
                href="/login"
                className="rounded-full border border-stone-900/10 bg-white px-6 py-3 text-sm font-semibold text-stone-700"
              >
                接続確認へ
              </Link>
            </div>
          </div>

          <div className="grid gap-4">
            <section className="rounded-[30px] border border-stone-900/10 bg-stone-900 p-6 text-stone-50 shadow-[0_30px_90px_-50px_rgba(28,25,23,0.9)]">
              <p className="text-xs uppercase tracking-[0.3em] text-stone-400">Flow</p>
              <ul className="mt-4 space-y-3 text-sm leading-7 text-stone-300">
                <li>1. トップページからログインへ進む</li>
                <li>2. Google ログインで権限を許可する</li>
                <li>3. 既存のアプリ画面で予定、取り込み、移動調整を使う</li>
              </ul>
            </section>

            <section className="rounded-[30px] border border-stone-900/10 bg-white/75 p-6 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
              <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Ready</p>
              <h3 className="mt-2 text-xl font-semibold">初回導線を切り分け済み</h3>
              <p className="mt-3 text-sm leading-7 text-stone-600">
                このページは公開トップ。ログイン後はアプリ側ホームへ移動する。
              </p>
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}
