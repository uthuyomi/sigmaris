import { createClient } from "@/lib/supabase/server";
import type { EventItem } from "@/lib/mock-schedule";

const APP_TIME_ZONE = "Asia/Tokyo";

type EventRow = {
  id: string;
  user_id?: string;
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

const getPartsInTimeZone = (value: string) => {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: APP_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });

  const parts = formatter.formatToParts(new Date(value));
  const read = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "00";

  return {
    year: read("year"),
    month: read("month"),
    day: read("day"),
    hour: Number(read("hour")),
    minute: Number(read("minute")),
  };
};

const toMinutesInTimeZone = (value: string) => {
  const parts = getPartsInTimeZone(value);
  return parts.hour * 60 + parts.minute;
};

const toIsoDateInTimeZone = (value: string) => {
  const parts = getPartsInTimeZone(value);
  return `${parts.year}-${parts.month}-${parts.day}`;
};

const startOfMonthInJst = (month: string) => `${month}-01T00:00:00+09:00`;

const nextMonthStartInJst = (month: string) => {
  const [year, monthValue] = month.split("-").map(Number);
  const nextYear = monthValue === 12 ? year + 1 : year;
  const nextMonth = monthValue === 12 ? 1 : monthValue + 1;
  return `${nextYear}-${`${nextMonth}`.padStart(2, "0")}-01T00:00:00+09:00`;
};

export const mapEventRowToEventItem = (row: EventRow): EventItem => {
  const startMinutes = toMinutesInTimeZone(row.starts_at);
  const endMinutes = toMinutesInTimeZone(row.ends_at);
  const date = toIsoDateInTimeZone(row.starts_at);

  return {
    id: row.id,
    title: row.title,
    startMinutes,
    endMinutes: Math.max(endMinutes, startMinutes + 30),
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
  const [year, month, day] = date.split("-").map(Number);
  const nextDay = new Date(Date.UTC(year, month - 1, day + 1, 0, 0, 0));
  const end = `${nextDay.getUTCFullYear()}-${`${nextDay.getUTCMonth() + 1}`.padStart(2, "0")}-${`${nextDay.getUTCDate()}`.padStart(2, "0")}T00:00:00+09:00`;

  return listEventsInRangeForUser(userId, start, end);
};

export const listEventsForMonthForUser = async (userId: string, month: string) => {
  return listEventsInRangeForUser(userId, startOfMonthInJst(month), nextMonthStartInJst(month));
};

export const getEventRowByIdForUser = async (userId: string, eventId: string) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("events")
    .select(
      "id,user_id,title,description,location_text,starts_at,ends_at,source_type,external_event_id,status,calendar_connection_id,metadata",
    )
    .eq("user_id", userId)
    .eq("id", eventId)
    .maybeSingle();

  if (error) {
    throw new Error(error.message);
  }

  return data;
};

export const listConflictingEventsForUser = async (input: {
  userId: string;
  startsAt: string;
  endsAt: string;
  excludeEventIds?: string[];
}) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("events")
    .select("id,title,starts_at,ends_at,location_text")
    .eq("user_id", input.userId)
    .neq("status", "cancelled")
    .lt("starts_at", input.endsAt)
    .gt("ends_at", input.startsAt)
    .order("starts_at", { ascending: true });

  if (error) {
    throw new Error(error.message);
  }

  return (data ?? []).filter((item) => !input.excludeEventIds?.includes(item.id));
};

export const createEventForUser = async (input: {
  userId: string;
  title: string;
  description?: string | null;
  locationText?: string | null;
  startsAt: string;
  endsAt: string;
  sourceType?: "manual" | "chat" | "sheet" | "image" | "calendar_sync";
  externalEventId?: string | null;
  calendarConnectionId?: string | null;
  metadata?: Record<string, unknown>;
}) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("events")
    .insert({
      user_id: input.userId,
      title: input.title,
      description: input.description ?? null,
      location_text: input.locationText ?? null,
      starts_at: input.startsAt,
      ends_at: input.endsAt,
      source_type: input.sourceType ?? "manual",
      external_event_id: input.externalEventId ?? null,
      calendar_connection_id: input.calendarConnectionId ?? null,
      metadata: input.metadata ?? {},
    })
    .select(
      "id,user_id,title,description,location_text,starts_at,ends_at,source_type,external_event_id,status,calendar_connection_id,metadata",
    )
    .single();

  if (error) {
    throw new Error(error.message);
  }

  return data;
};

export const replaceTravelPlanForEvent = async (input: {
  eventId: string;
  originLabel: string;
  originAddress: string;
  destinationLabel: string;
  destinationAddress: string;
  travelMode: "transit" | "driving" | "walking";
  recommendedDepartureAt?: string;
  estimatedArrivalAt?: string;
  durationMinutes?: number;
  routeSummary?: string;
  routeSteps: unknown[];
}) => {
  const supabase = await createClient();
  const { error: deleteError } = await supabase
    .from("event_travel_plans")
    .delete()
    .eq("event_id", input.eventId);

  if (deleteError) {
    throw new Error(deleteError.message);
  }

  const { error } = await supabase.from("event_travel_plans").insert({
    event_id: input.eventId,
    origin_label: input.originLabel,
    origin_address: input.originAddress,
    destination_label: input.destinationLabel,
    destination_address: input.destinationAddress,
    travel_mode: input.travelMode,
    recommended_departure_at: input.recommendedDepartureAt ?? null,
    estimated_arrival_at: input.estimatedArrivalAt ?? null,
    duration_minutes: input.durationMinutes ?? null,
    route_summary: input.routeSummary ?? null,
    route_steps: input.routeSteps,
  });

  if (error) {
    throw new Error(error.message);
  }
};
