"use client";
// 役割: タイムラインの日別グリッドを描画するReactコンポーネント。


import Link from "next/link";
import { useMemo } from "react";
import { TimelineEventCard } from "@/components/timeline/timeline-event-card";
import { minutesToLabel, type EventItem, type Grain } from "@/lib/mock-schedule";

type TimelineDayGridProps = {
  activeGrain: Grain;
  backLabel: string;
  dateLabel: string;
  events: EventItem[];
  placeLabel: string;
  selectedEvent?: EventItem;
  selectedEventId: string | null;
  sourceAppLabel: string;
  sourceSyncLabel: string;
  onSelectEvent: (eventId: string | null) => void;
};

const pixelsPerMinuteForGrain = (grain: Grain) => (grain <= 10 ? 1.6 : grain <= 15 ? 1.25 : 0.95);

export function TimelineDayGrid({
  activeGrain,
  backLabel,
  dateLabel,
  events,
  placeLabel,
  selectedEvent,
  selectedEventId,
  sourceAppLabel,
  sourceSyncLabel,
  onSelectEvent,
}: TimelineDayGridProps) {
  const pixelsPerMinute = pixelsPerMinuteForGrain(activeGrain);
  const lastEventEndMinutes = events.reduce(
    (latest, event) => Math.max(latest, event.endMinutes),
    24 * 60,
  );
  const timelineHeight = lastEventEndMinutes * pixelsPerMinute;
  const slots = useMemo(() => {
    const total = Math.ceil(lastEventEndMinutes / activeGrain);
    return Array.from({ length: total }, (_, index) => index * activeGrain);
  }, [activeGrain, lastEventEndMinutes]);

  return (
    <div className="overflow-hidden rounded-2xl border border-stone-900/10 bg-[#fcfbf7] dark:border-white/10 dark:bg-[#212121]">
      <div className="flex items-center justify-between border-b border-stone-900/8 px-4 py-3 dark:border-white/10">
        <div>
          <p className="text-sm font-semibold text-stone-900 dark:text-stone-50">{dateLabel}</p>
          <p className="text-xs text-stone-500 dark:text-stone-400">{events.length}</p>
        </div>
        <Link
          href="/calendar"
          className="rounded-full border border-stone-900/10 bg-white px-3 py-2 text-xs font-medium text-stone-700 transition hover:bg-stone-50 dark:border-white/10 dark:bg-white/8 dark:text-stone-200 dark:hover:bg-white/12"
        >
          {backLabel}
        </Link>
      </div>

      <div className="h-[42rem] overflow-y-auto px-3 py-4 sm:px-4">
        <div className="relative" style={{ height: `${timelineHeight}px` }}>
          {slots.map((minute) => {
            const isHourBoundary = minute % 60 === 0;
            const top = minute * pixelsPerMinute;

            return (
              <div key={minute} className="absolute inset-x-0" style={{ top: `${top}px` }}>
                <div className="grid grid-cols-[60px_minmax(0,1fr)] items-start gap-3">
                  <div className="pr-2 text-right">
                    {isHourBoundary ? (
                      <span className="text-xs font-semibold tracking-[0.18em] text-stone-400">
                        {minutesToLabel(minute)}
                      </span>
                    ) : null}
                  </div>
                  <div className={`h-px ${isHourBoundary ? "bg-stone-900/14 dark:bg-white/14" : "bg-stone-900/6 dark:bg-white/6"}`} />
                </div>
              </div>
            );
          })}

          <div className="absolute inset-y-0 left-[72px] right-0">
            {events.map((event) => {
              const expanded = selectedEventId === event.id;

              return (
                <TimelineEventCard
                  key={event.id}
                  event={event}
                  expanded={expanded}
                  selected={selectedEvent?.id === event.id}
                  pixelsPerMinute={pixelsPerMinute}
                  sourceSyncLabel={sourceSyncLabel}
                  sourceAppLabel={sourceAppLabel}
                  placeLabel={placeLabel}
                  onToggle={() => onSelectEvent(expanded ? null : event.id)}
                />
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
