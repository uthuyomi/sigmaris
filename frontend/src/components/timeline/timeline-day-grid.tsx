"use client";
// 役割: タイムラインの日別グリッドを描画するReactコンポーネント。


import Link from "next/link";
import { useMemo } from "react";
import { TimelineEventCard } from "@/components/timeline/timeline-event-card";
import type { EventItem, Grain } from "@/lib/mock-schedule";

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
  const slots = useMemo(() => {
    const total = (24 * 60) / activeGrain;
    return Array.from({ length: total }, (_, index) => index * activeGrain);
  }, [activeGrain]);

  const pixelsPerMinute = pixelsPerMinuteForGrain(activeGrain);
  const timelineHeight = 24 * 60 * pixelsPerMinute;

  return (
    <div className="overflow-hidden rounded-[28px] border border-stone-900/10 bg-[#fcfbf7]">
      <div className="flex items-center justify-between border-b border-stone-900/8 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-stone-900">{dateLabel}</p>
          <p className="text-xs text-stone-500">{events.length}</p>
        </div>
        <Link
          href="/calendar"
          className="rounded-full border border-stone-900/10 bg-white px-3 py-2 text-xs font-medium text-stone-700 transition hover:bg-stone-50"
        >
          {backLabel}
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
                  <div className={`h-px ${isHourBoundary ? "bg-stone-900/14" : "bg-stone-900/6"}`} />
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
