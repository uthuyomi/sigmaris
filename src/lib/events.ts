import { createClient } from "@/lib/supabase/server";
import type { EventItem } from "@/lib/mock-schedule";

type EventRow = {
  id: string;
  title: string;
  description: string | null;
  location_text: string | null;
  starts_at: string;
  ends_at: string;
  source_type: "manual" | "chat" | "sheet" | "image" | "calendar_sync";
  external_event_id: string | null;
};

const toneBySource: Record<EventRow["source_type"], EventItem["tone"]> = {
  manual: "sky",
  chat: "mint",
  sheet: "amber",
  image: "amber",
  calendar_sync: "sky",
};

const toMinutes = (date: Date) => date.getHours() * 60 + date.getMinutes();

export const mapEventRowToEventItem = (row: EventRow): EventItem => {
  const startsAt = new Date(row.starts_at);
  const endsAt = new Date(row.ends_at);
  const date = row.starts_at.slice(0, 10);

  return {
    id: row.id,
    title: row.title,
    startMinutes: toMinutes(startsAt),
    endMinutes: Math.max(toMinutes(endsAt), toMinutes(startsAt) + 30),
    tone: toneBySource[row.source_type] ?? "sky",
    detail:
      row.description ?? (row.source_type === "calendar_sync" ? "Synced from Google Calendar" : "Scheduled"),
    date,
    location: row.location_text ?? undefined,
    externalEventId: row.external_event_id ?? undefined,
    sourceType: row.source_type,
  };
};

export const listEventsInRangeForUser = async (userId: string, fromIso: string, toIso: string) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("events")
    .select(
      "id,title,description,location_text,starts_at,ends_at,source_type,external_event_id",
    )
    .eq("user_id", userId)
    .neq("status", "cancelled")
    .gte("starts_at", fromIso)
    .lt("starts_at", toIso)
    .order("starts_at", { ascending: true });

  if (error) {
    throw new Error(error.message);
  }

  return ((data ?? []) as EventRow[]).map(mapEventRowToEventItem);
};

export const listEventsForDateForUser = async (userId: string, date: string) => {
  const start = `${date}T00:00:00+09:00`;
  const endDate = new Date(`${date}T00:00:00+09:00`);
  endDate.setDate(endDate.getDate() + 1);
  const end = endDate.toISOString();

  return listEventsInRangeForUser(userId, start, end);
};

export const listEventsForMonthForUser = async (userId: string, month: string) => {
  const [year, monthValue] = month.split("-").map(Number);
  const start = new Date(year, monthValue - 1, 1);
  const end = new Date(year, monthValue, 1);

  return listEventsInRangeForUser(userId, start.toISOString(), end.toISOString());
};
