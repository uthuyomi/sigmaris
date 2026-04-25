"use client";
// 役割: 予定を時系列で表示するタイムライン画面のReactコンポーネント。


import { useState } from "react";
import { TimelineDayGrid } from "@/components/timeline/timeline-day-grid";
import { TimelineSidePanel } from "@/components/timeline/timeline-side-panel";
import { getDictionary, type AppLocale } from "@/lib/i18n";
import {
  formatJapaneseDate,
  grainOptions,
  type EventItem,
  type Grain,
} from "@/lib/mock-schedule";

type TimelineBoardProps = {
  locale: AppLocale;
  selectedDate?: string;
  events: EventItem[];
};

export function TimelineBoard({
  locale,
  selectedDate = "2026-03-27",
  events,
}: TimelineBoardProps) {
  const dict = getDictionary(locale);
  const [activeGrain, setActiveGrain] = useState<Grain>(10);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const selectedEvent =
    events.find((event) => event.id === selectedEventId) ??
    events.find((event) => event.location) ??
    events[0];
  const dateLabel = formatJapaneseDate(selectedDate);

  return (
    <div className="flex min-h-[42rem] flex-col overflow-hidden rounded-[32px] border border-stone-900/10 bg-white/80 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
      <div className="border-b border-stone-900/10 px-5 py-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.3em] text-stone-500">
              {dict.timeline.selectedDay}
            </p>
            <h2 className="mt-1 text-xl font-semibold text-stone-900">{dateLabel}</h2>
          </div>

          <div className="flex flex-wrap gap-2">
            {grainOptions.map((grain) => (
              <button
                key={grain}
                type="button"
                onClick={() => setActiveGrain(grain)}
                aria-label={`${grain}`}
                className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                  activeGrain === grain
                    ? "bg-stone-900 text-stone-50 shadow-[0_16px_35px_-24px_rgba(28,25,23,0.9)]"
                    : "bg-stone-900/5 text-stone-700 hover:bg-stone-900/10"
                }`}
              >
                {grain === 60 ? "1h" : `${grain}m`}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-4 border-b border-stone-900/10 px-5 py-4 md:grid-cols-[1.3fr_0.9fr]">
        <div className="rounded-[24px] bg-stone-900 px-4 py-4 text-stone-50">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-400">{dict.timeline.title}</p>
          <p className="mt-2 text-lg font-semibold">{dateLabel}</p>
          <p className="mt-2 text-sm leading-7 text-stone-200">{dict.timeline.refine}</p>
        </div>
        <div className="rounded-[24px] border border-stone-900/10 bg-stone-50 px-4 py-4">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-500">{dict.timeline.selectedGrain}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-stone-900">
            {activeGrain === 60 ? "1h" : `${activeGrain}m`}
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-hidden p-4">
        <div className="grid h-full gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
          <TimelineDayGrid
            activeGrain={activeGrain}
            backLabel={dict.common.backToCalendar}
            dateLabel={dateLabel}
            events={events}
            placeLabel={dict.timeline.place}
            selectedEvent={selectedEvent}
            selectedEventId={selectedEventId}
            sourceAppLabel={dict.timeline.sourceApp}
            sourceSyncLabel={dict.timeline.sourceSync}
            onSelectEvent={setSelectedEventId}
          />

          <TimelineSidePanel
            locale={locale}
            event={selectedEvent}
            labels={{
              end: dict.timeline.end,
              humanLogic: dict.timeline.humanLogic,
              place: dict.timeline.place,
              quickEdit: dict.timeline.quickEdit,
              sourceApp: dict.timeline.sourceApp,
              sourceSync: dict.timeline.sourceSync,
              start: dict.timeline.start,
            }}
            logicItems={dict.timeline.logicItems}
          />
        </div>
      </div>
    </div>
  );
}
