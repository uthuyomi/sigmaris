// 役割: Supabaseの行データとアプリ内のEventItemを相互変換する。

import type { EventItem } from "@/lib/mock-schedule";
import type { EventRow } from "@/lib/event-data/types";
import { toIsoDateInTimeZone, toMinutesInTimeZone } from "@/lib/event-data/time";

const toneBySource: Record<EventRow["source_type"], EventItem["tone"]> = {
  manual: "sky",
  chat: "mint",
  sheet: "amber",
  image: "amber",
  calendar_sync: "sky",
};

const isTravelBlockEvent = (row: EventRow) =>
  row.metadata?.kind === "travel_block" ||
  row.title.toLowerCase().startsWith("travel:") ||
  row.title.startsWith("移動");

export const mapEventRowToEventItem = (row: EventRow): EventItem => {
  const startMinutes = toMinutesInTimeZone(row.starts_at);
  const endMinutes = toMinutesInTimeZone(row.ends_at);
  const date = toIsoDateInTimeZone(row.starts_at);
  const isTravelBlock = isTravelBlockEvent(row);
  const displayEndMinutes = isTravelBlock
    ? Math.max(endMinutes, startMinutes + 1)
    : Math.max(endMinutes, startMinutes + 30);

  return {
    id: row.id,
    title: row.title,
    startMinutes,
    endMinutes: displayEndMinutes,
    tone: toneBySource[row.source_type] ?? "sky",
    detail:
      row.description ?? (row.source_type === "calendar_sync" ? "Synced from Google Calendar" : "Scheduled"),
    date,
    location: row.location_text ?? undefined,
    externalEventId: row.external_event_id ?? undefined,
    sourceType: row.source_type,
  };
};
