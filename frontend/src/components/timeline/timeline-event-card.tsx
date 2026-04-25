"use client";
// 役割: タイムライン上の予定カードを表示するReactコンポーネント。


import { minutesToLabel, toneClassMap, type EventItem } from "@/lib/mock-schedule";

type TimelineEventCardProps = {
  event: EventItem;
  expanded: boolean;
  selected: boolean;
  pixelsPerMinute: number;
  sourceSyncLabel: string;
  sourceAppLabel: string;
  placeLabel: string;
  onToggle: () => void;
};

export function TimelineEventCard({
  event,
  expanded,
  selected,
  pixelsPerMinute,
  sourceSyncLabel,
  sourceAppLabel,
  placeLabel,
  onToggle,
}: TimelineEventCardProps) {
  const top = event.startMinutes * pixelsPerMinute;
  const height = Math.max((event.endMinutes - event.startMinutes) * pixelsPerMinute, 48);
  const compact = height < 96;

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      aria-pressed={selected}
      className={`absolute left-3 right-3 rounded-[22px] border px-4 py-3 text-left outline-none transition hover:-translate-y-0.5 focus-visible:ring-3 focus-visible:ring-stone-900/30 ${
        selected ? "z-20 ring-3 ring-stone-900/18" : "z-10"
      } ${
        expanded
          ? "z-30 overflow-visible shadow-[0_24px_65px_-34px_rgba(28,25,23,0.8)]"
          : "overflow-hidden"
      } ${toneClassMap[event.tone]}`}
      style={expanded ? { top: `${top}px`, minHeight: `${height}px` } : { top: `${top}px`, height: `${height}px` }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={`text-sm font-semibold leading-6 ${expanded ? "whitespace-normal break-words" : "truncate"}`}>
            {event.title}
          </p>
          <p className="mt-1 text-xs font-medium uppercase tracking-[0.18em] opacity-70">
            {minutesToLabel(event.startMinutes)} - {minutesToLabel(event.endMinutes)}
          </p>
          {event.location && (!compact || expanded) ? (
            <p className="mt-2 break-words text-xs font-medium leading-5 opacity-70">
              {placeLabel}: {event.location}
            </p>
          ) : null}
        </div>
        <div className="shrink-0 rounded-full bg-white/50 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]">
          {event.sourceType === "calendar_sync" ? sourceSyncLabel : sourceAppLabel}
        </div>
      </div>

      {!compact || expanded ? (
        <p className={`mt-3 text-sm leading-6 opacity-85 ${expanded ? "whitespace-pre-wrap break-words" : "line-clamp-2"}`}>
          {event.detail}
        </p>
      ) : null}
    </button>
  );
}
