"use client";
// 役割: タイムライン画面の補助情報や操作パネルを表示するReactコンポーネント。


import { MobilityPanel } from "@/components/mobility-panel";
import { minutesToLabel, type EventItem } from "@/lib/mock-schedule";
import type { AppLocale } from "@/lib/i18n";

type TimelineSidePanelProps = {
  locale: AppLocale;
  event?: EventItem;
  labels: {
    end: string;
    humanLogic: string;
    place: string;
    quickEdit: string;
    sourceApp: string;
    sourceSync: string;
    start: string;
  };
  logicItems: string[];
};

export function TimelineSidePanel({ locale, event, labels, logicItems }: TimelineSidePanelProps) {
  return (
    <aside className="flex flex-col gap-4">
      <section className="rounded-2xl border border-stone-900/10 bg-stone-50 p-4 dark:border-white/10 dark:bg-white/6">
        <p className="text-xs uppercase tracking-[0.3em] text-stone-500 dark:text-stone-400">{labels.quickEdit}</p>
        {event ? (
          <div className="mt-4 rounded-2xl border border-stone-900/10 bg-white px-4 py-4 dark:border-white/10 dark:bg-[#2f2f2f]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-stone-900 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-stone-50">
                {event.sourceType === "calendar_sync" ? labels.sourceSync : labels.sourceApp}
              </span>
              <span className="text-xs font-medium text-stone-500 dark:text-stone-400">
                {minutesToLabel(event.startMinutes)} - {minutesToLabel(event.endMinutes)}
              </span>
            </div>
            <h3 className="mt-3 break-words text-base font-semibold leading-7 text-stone-900 dark:text-stone-50">{event.title}</h3>
            {event.location ? (
              <p className="mt-3 break-words text-sm leading-7 text-stone-700 dark:text-stone-300">
                {labels.place}: {event.location}
              </p>
            ) : null}
            <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-stone-700 dark:text-stone-300">{event.detail}</p>
          </div>
        ) : null}

        <div className="mt-4 space-y-3">
          <label className="block">
            <span className="mb-2 block text-xs font-medium uppercase tracking-[0.18em] text-stone-500 dark:text-stone-400">
              {labels.start}
            </span>
            <div className="rounded-2xl border border-stone-900/10 bg-white px-4 py-3 text-sm text-stone-900 dark:border-white/10 dark:bg-[#2f2f2f] dark:text-stone-100">
              {event ? minutesToLabel(event.startMinutes) : "--:--"}
            </div>
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-medium uppercase tracking-[0.18em] text-stone-500 dark:text-stone-400">
              {labels.end}
            </span>
            <div className="rounded-2xl border border-stone-900/10 bg-white px-4 py-3 text-sm text-stone-900 dark:border-white/10 dark:bg-[#2f2f2f] dark:text-stone-100">
              {event ? minutesToLabel(event.endMinutes) : "--:--"}
            </div>
          </label>
        </div>
      </section>

      <MobilityPanel locale={locale} selectedEvent={event} />

      <section className="rounded-2xl border border-stone-900/10 bg-white p-4 dark:border-white/10 dark:bg-white/6">
        <p className="text-xs uppercase tracking-[0.3em] text-stone-500 dark:text-stone-400">{labels.humanLogic}</p>
        <ul className="mt-3 space-y-3 text-sm leading-6 text-stone-700 dark:text-stone-300">
          {logicItems.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
