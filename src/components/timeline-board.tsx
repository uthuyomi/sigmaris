"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { MobilityPanel } from "@/components/mobility-panel";
import {
  formatJapaneseDate,
  getEventsByDate,
  grainOptions,
  minutesToLabel,
  toneClassMap,
  type EventItem,
  type Grain,
} from "@/lib/mock-schedule";

type TimelineBoardProps = {
  selectedDate?: string;
};

export function TimelineBoard({
  selectedDate = "2026-03-27",
}: TimelineBoardProps) {
  const [activeGrain, setActiveGrain] = useState<Grain>(10);

  const slots = useMemo(() => {
    const total = (24 * 60) / activeGrain;
    return Array.from({ length: total }, (_, index) => index * activeGrain);
  }, [activeGrain]);

  const pixelsPerMinute = activeGrain <= 10 ? 1.6 : activeGrain <= 15 ? 1.25 : 0.95;
  const timelineHeight = 24 * 60 * pixelsPerMinute;
  const selectedEvents = getEventsByDate(selectedDate);
  const focusEvent: EventItem | undefined =
    selectedEvents.find((event) => event.location) ?? selectedEvents[0];
  const dateLabel = formatJapaneseDate(selectedDate);

  return (
    <div className="flex min-h-[42rem] flex-col overflow-hidden rounded-[32px] border border-stone-900/10 bg-white/75 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
      <div className="border-b border-stone-900/10 px-5 py-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.3em] text-stone-500">
              Timeline
            </p>
            <h2 className="mt-1 text-lg font-semibold text-stone-900">
              1日の流れを 24 時間で調整
            </h2>
            <p className="mt-2 text-sm text-stone-600">
              カレンダーで日付を選んでから、その日の予定だけに集中して細かく詰める。
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
          <p className="text-xs uppercase tracking-[0.3em] text-stone-400">Selected day</p>
          <p className="mt-2 text-lg font-semibold">{dateLabel}</p>
          <p className="mt-2 text-sm leading-7 text-stone-200">
            デフォルトは 10 分刻み。細かく詰めたいときだけ 5 分へ寄せる。
          </p>
        </div>
        <div className="rounded-[24px] border border-stone-900/10 bg-stone-50 px-4 py-4">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Selected grain</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-stone-900">
            {activeGrain === 60 ? "1時間" : `${activeGrain}分`}
          </p>
          <p className="mt-2 text-sm leading-6 text-stone-600">
            スナップと並びの密度をここで切り替える。
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-hidden p-4">
        <div className="grid h-full gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="overflow-hidden rounded-[28px] border border-stone-900/10 bg-[#fcfbf7]">
            <div className="flex items-center justify-between border-b border-stone-900/8 px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-stone-900">{dateLabel}</p>
                <p className="text-xs text-stone-500">カレンダーから選んだ日のタイムライン</p>
              </div>
              <Link
                href="/calendar"
                className="rounded-full border border-stone-900/10 bg-white px-3 py-2 text-xs font-medium text-stone-700 transition hover:bg-stone-50"
              >
                カレンダーへ戻る
              </Link>
            </div>

            <div className="h-[42rem] overflow-y-auto px-3 py-4 sm:px-4">
              <div className="relative" style={{ height: `${timelineHeight}px` }}>
                {slots.map((minute) => {
                  const hour = Math.floor(minute / 60);
                  const isHourBoundary = minute % 60 === 0;
                  const top = minute * pixelsPerMinute;

                  return (
                    <div key={minute} className="absolute inset-x-0" style={{ top: `${top}px` }}>
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
                  {selectedEvents.map((event) => {
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
                            {event.location ? (
                              <p className="mt-2 text-xs font-medium opacity-70">
                                場所: {event.location}
                              </p>
                            ) : null}
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
              <h3 className="mt-2 text-base font-semibold text-stone-900">選択中の枠を調整</h3>
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
                この時間で調整
              </button>
            </section>

            <MobilityPanel selectedEvent={focusEvent} />

            <section className="rounded-[28px] border border-stone-900/10 bg-[linear-gradient(180deg,_rgba(231,111,81,0.12),_rgba(255,255,255,0.92))] p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Human logic</p>
              <ul className="mt-3 space-y-3 text-sm leading-6 text-stone-700">
                <li>まず日付はカレンダーで決める。</li>
                <li>時間の調整はタイムラインに集中させる。</li>
                <li>移動がある日は、推奨出発時刻まで含めて考える。</li>
              </ul>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}
