"use client";

import { useMemo, useState } from "react";

type Grain = 5 | 10 | 15 | 30 | 60;

type EventItem = {
  id: string;
  title: string;
  startMinutes: number;
  endMinutes: number;
  tone: "mint" | "amber" | "sky";
  detail: string;
};

const grainOptions: Grain[] = [5, 10, 15, 30, 60];

const messages = [
  {
    id: "m1",
    role: "assistant",
    text: "おはよう。今日は移動込みで詰まりやすいね。午前は作業、夕方に打ち合わせを寄せると安定しそうだよ。",
  },
  {
    id: "m2",
    role: "user",
    text: "10時から集中作業、16時台に30分の相談枠を入れたい。",
  },
  {
    id: "m3",
    role: "assistant",
    text: "了解。10:00から深めの作業ブロック、16:20から相談枠で仮置きしてある。下のタイムラインで細かく調整できるよ。",
  },
];

const quickActions = [
  "空き時間を探す",
  "午後の予定を圧縮",
  "5分刻みに切り替え",
  "移動時間も含める",
];

const events: EventItem[] = [
  {
    id: "e1",
    title: "朝の確認と連絡整理",
    startMinutes: 8 * 60 + 30,
    endMinutes: 9 * 60 + 10,
    tone: "mint",
    detail: "Slack / メール / 本日の優先順位",
  },
  {
    id: "e2",
    title: "集中作業ブロック",
    startMinutes: 10 * 60,
    endMinutes: 12 * 60 + 10,
    tone: "sky",
    detail: "UI 実装とタイムライン調整",
  },
  {
    id: "e3",
    title: "相談枠",
    startMinutes: 16 * 60 + 20,
    endMinutes: 16 * 60 + 50,
    tone: "amber",
    detail: "進捗確認 / 次の調整",
  },
  {
    id: "e4",
    title: "夜の整理",
    startMinutes: 21 * 60,
    endMinutes: 21 * 60 + 45,
    tone: "mint",
    detail: "明日の仮配置を作る",
  },
];

const toneClassMap: Record<EventItem["tone"], string> = {
  mint: "border-lime-400/80 bg-lime-200/85 text-lime-950 shadow-[0_18px_40px_-24px_rgba(132,204,22,0.75)]",
  amber:
    "border-amber-400/80 bg-amber-200/90 text-amber-950 shadow-[0_18px_40px_-24px_rgba(245,158,11,0.75)]",
  sky: "border-sky-400/80 bg-sky-200/90 text-sky-950 shadow-[0_18px_40px_-24px_rgba(56,189,248,0.75)]",
};

const minutesToLabel = (value: number) => {
  const hours = Math.floor(value / 60);
  const minutes = value % 60;

  return `${hours.toString().padStart(2, "0")}:${minutes
    .toString()
    .padStart(2, "0")}`;
};

export function SchedulerDemo() {
  const [activeGrain, setActiveGrain] = useState<Grain>(10);

  const slots = useMemo(() => {
    const total = (24 * 60) / activeGrain;

    return Array.from({ length: total }, (_, index) => index * activeGrain);
  }, [activeGrain]);

  const pixelsPerMinute = activeGrain <= 10 ? 1.6 : activeGrain <= 15 ? 1.25 : 0.95;
  const timelineHeight = 24 * 60 * pixelsPerMinute;

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(244,162,97,0.22),_transparent_28%),linear-gradient(180deg,_#f8f5ee_0%,_#efe6d3_52%,_#e7dcc5_100%)] text-stone-900">
      <div className="mx-auto flex min-h-screen w-full max-w-[1500px] flex-col px-4 pb-24 pt-4 sm:px-6 lg:px-8">
        <div className="mb-4 flex items-center justify-between rounded-[28px] border border-stone-900/10 bg-white/70 px-4 py-3 shadow-[0_20px_60px_-40px_rgba(41,37,36,0.55)] backdrop-blur">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.3em] text-stone-500">
              ShiftPilotAI
            </p>
            <h1 className="font-sans text-xl font-semibold tracking-tight sm:text-2xl">
              チャットで組んで、タイムラインで詰める
            </h1>
          </div>
          <div className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50">
            今日は 4 件の予定
          </div>
        </div>

        <section className="grid flex-1 gap-4 lg:grid-cols-[420px_minmax(0,1fr)]">
          <div className="flex min-h-[38rem] flex-col overflow-hidden rounded-[32px] border border-stone-900/10 bg-[linear-gradient(180deg,_rgba(35,31,32,0.96),_rgba(54,48,42,0.92))] text-stone-50 shadow-[0_30px_90px_-50px_rgba(28,25,23,0.9)]">
            <div className="border-b border-white/10 px-5 py-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-stone-400">
                    Assistant
                  </p>
                  <h2 className="mt-1 text-lg font-semibold">予定調整チャット</h2>
                </div>
                <div className="rounded-full border border-white/15 px-3 py-1 text-xs text-stone-300">
                  進行中
                </div>
              </div>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto px-4 py-5">
              {messages.map((message) => (
                <article
                  key={message.id}
                  className={`max-w-[88%] rounded-[24px] px-4 py-3 text-sm leading-7 shadow-[0_20px_45px_-35px_rgba(0,0,0,0.9)] ${
                    message.role === "assistant"
                      ? "rounded-bl-md bg-white/10 text-stone-100"
                      : "ml-auto rounded-br-md bg-[#f4a261] text-stone-950"
                  }`}
                >
                  {message.text}
                </article>
              ))}
            </div>

            <div className="border-t border-white/10 px-4 py-4">
              <div className="mb-3 flex flex-wrap gap-2">
                {quickActions.map((action) => (
                  <button
                    key={action}
                    type="button"
                    className="rounded-full border border-white/10 bg-white/8 px-3 py-2 text-xs font-medium text-stone-200 transition hover:bg-white/14"
                  >
                    {action}
                  </button>
                ))}
              </div>

              <div className="rounded-[26px] border border-white/10 bg-black/20 p-3">
                <div className="rounded-[20px] bg-white/7 px-4 py-3 text-sm text-stone-300">
                  明日の午前を少し前倒しして、16:20 の相談枠を維持したい
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <p className="text-xs text-stone-400">候補を出してからタイムラインで微調整</p>
                  <button
                    type="button"
                    className="rounded-full bg-[#e76f51] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#d95f42]"
                  >
                    送信
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div className="flex min-h-[38rem] flex-col overflow-hidden rounded-[32px] border border-stone-900/10 bg-white/75 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
            <div className="border-b border-stone-900/10 px-5 py-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.3em] text-stone-500">
                    Timeline
                  </p>
                  <h2 className="mt-1 text-lg font-semibold text-stone-900">
                    1日の流れを 24 時間で確認
                  </h2>
                  <p className="mt-2 text-sm text-stone-600">
                    タップで仮予定、ドラッグで調整、細かい補正は数値入力に逃がす設計を前提にしているよ。
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  {grainOptions.map((grain) => (
                    <button
                      key={grain}
                      type="button"
                      onClick={() => setActiveGrain(grain)}
                      className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                        activeGrain === grain
                          ? "bg-stone-900 text-stone-50 shadow-[0_16px_35px_-24px_rgba(28,25,23,0.9)]"
                          : "bg-stone-900/5 text-stone-700 hover:bg-stone-900/10"
                      }`}
                    >
                      {grain === 60 ? "1時間" : `${grain}分`}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid gap-4 border-b border-stone-900/10 px-5 py-4 md:grid-cols-[1.3fr_0.9fr]">
              <div className="rounded-[24px] bg-stone-900 px-4 py-4 text-stone-50">
                <p className="text-xs uppercase tracking-[0.3em] text-stone-400">Today&apos;s logic</p>
                <p className="mt-2 text-sm leading-7 text-stone-200">
                  デフォルトは 10 分刻み。細かく詰めたいときだけ 5 分へ寄せて、普段は視認性を優先する。
                </p>
              </div>
              <div className="rounded-[24px] border border-stone-900/10 bg-stone-50 px-4 py-4">
                <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Selected grain</p>
                <p className="mt-2 text-3xl font-semibold tracking-tight text-stone-900">
                  {activeGrain === 60 ? "1時間" : `${activeGrain}分`}
                </p>
                <p className="mt-2 text-sm leading-6 text-stone-600">
                  スナップと目盛りの密度をここで切り替える。
                </p>
              </div>
            </div>

            <div className="flex-1 overflow-hidden p-4">
              <div className="grid h-full gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
                <div className="overflow-hidden rounded-[28px] border border-stone-900/10 bg-[#fcfbf7]">
                  <div className="flex items-center justify-between border-b border-stone-900/8 px-4 py-3">
                    <div>
                      <p className="text-sm font-semibold text-stone-900">2026年3月27日 金曜日</p>
                      <p className="text-xs text-stone-500">縦スクロールのデイタイムライン</p>
                    </div>
                    <button
                      type="button"
                      className="rounded-full border border-stone-900/10 bg-white px-3 py-2 text-xs font-medium text-stone-700 transition hover:bg-stone-50"
                    >
                      仮予定を追加
                    </button>
                  </div>

                  <div className="h-[38rem] overflow-y-auto px-3 py-4 sm:px-4">
                    <div className="relative" style={{ height: `${timelineHeight}px` }}>
                      {slots.map((minute) => {
                        const hour = Math.floor(minute / 60);
                        const isHourBoundary = minute % 60 === 0;
                        const top = minute * pixelsPerMinute;

                        return (
                          <div
                            key={minute}
                            className="absolute inset-x-0"
                            style={{ top: `${top}px` }}
                          >
                            <div className="grid grid-cols-[60px_minmax(0,1fr)] items-start gap-3">
                              <div className="pr-2 text-right">
                                {isHourBoundary ? (
                                  <span className="text-xs font-semibold tracking-[0.18em] text-stone-400">
                                    {`${hour.toString().padStart(2, "0")}:00`}
                                  </span>
                                ) : null}
                              </div>
                              <div
                                className={`h-px ${
                                  isHourBoundary ? "bg-stone-900/14" : "bg-stone-900/6"
                                }`}
                              />
                            </div>
                          </div>
                        );
                      })}

                      <div className="absolute inset-y-0 left-[72px] right-0">
                        {events.map((event) => {
                          const top = event.startMinutes * pixelsPerMinute;
                          const height = Math.max(
                            (event.endMinutes - event.startMinutes) * pixelsPerMinute,
                            48,
                          );

                          return (
                            <article
                              key={event.id}
                              className={`absolute left-3 right-3 rounded-[22px] border px-4 py-3 ${toneClassMap[event.tone]}`}
                              style={{ top: `${top}px`, height: `${height}px` }}
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <p className="text-sm font-semibold leading-6">{event.title}</p>
                                  <p className="mt-1 text-xs font-medium uppercase tracking-[0.18em] opacity-70">
                                    {minutesToLabel(event.startMinutes)} -{" "}
                                    {minutesToLabel(event.endMinutes)}
                                  </p>
                                </div>
                                <div className="rounded-full bg-white/50 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]">
                                  Snap
                                </div>
                              </div>
                              <p className="mt-3 text-sm leading-6 opacity-85">{event.detail}</p>
                            </article>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </div>

                <aside className="flex flex-col gap-4">
                  <section className="rounded-[28px] border border-stone-900/10 bg-stone-50 p-4">
                    <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Quick edit</p>
                    <h3 className="mt-2 text-base font-semibold text-stone-900">相談枠を微調整</h3>
                    <div className="mt-4 space-y-3">
                      <label className="block">
                        <span className="mb-2 block text-xs font-medium uppercase tracking-[0.18em] text-stone-500">
                          開始
                        </span>
                        <div className="rounded-2xl border border-stone-900/10 bg-white px-4 py-3 text-sm text-stone-900">
                          16:20
                        </div>
                      </label>
                      <label className="block">
                        <span className="mb-2 block text-xs font-medium uppercase tracking-[0.18em] text-stone-500">
                          終了
                        </span>
                        <div className="rounded-2xl border border-stone-900/10 bg-white px-4 py-3 text-sm text-stone-900">
                          16:50
                        </div>
                      </label>
                    </div>
                    <button
                      type="button"
                      className="mt-4 w-full rounded-full bg-stone-900 px-4 py-3 text-sm font-semibold text-stone-50 transition hover:bg-stone-800"
                    >
                      この時間で確定
                    </button>
                  </section>

                  <section className="rounded-[28px] border border-stone-900/10 bg-[linear-gradient(180deg,_rgba(231,111,81,0.12),_rgba(255,255,255,0.92))] p-4">
                    <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Human logic</p>
                    <ul className="mt-3 space-y-3 text-sm leading-6 text-stone-700">
                      <li>粗く見たいときは 30 分か 1 時間で流れを掴む。</li>
                      <li>普段の編集は 10 分で十分速い。</li>
                      <li>詰める場面だけ 5 分へ落とすと認知負荷が低い。</li>
                    </ul>
                  </section>
                </aside>
              </div>
            </div>
          </div>
        </section>

        <nav className="fixed bottom-4 left-1/2 z-20 flex w-[min(92vw,28rem)] -translate-x-1/2 items-center justify-between rounded-full border border-stone-900/10 bg-white/90 px-4 py-3 shadow-[0_25px_70px_-35px_rgba(28,25,23,0.7)] backdrop-blur lg:hidden">
          {["ホーム", "チャット", "予定", "設定"].map((item) => (
            <button
              key={item}
              type="button"
              className={`rounded-full px-4 py-2 text-sm font-medium ${
                item === "チャット" ? "bg-stone-900 text-stone-50" : "text-stone-600"
              }`}
            >
              {item}
            </button>
          ))}
        </nav>
      </div>
    </main>
  );
}
