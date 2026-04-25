// 役割: 予定データをSupabaseのDBから取得する処理をまとめる。

import { mapEventRowToEventItem } from "@/lib/event-data/mapper";
import { nextDayStartInJst, nextMonthStartInJst, startOfMonthInJst } from "@/lib/event-data/time";
import type { EventRow } from "@/lib/event-data/types";
import { createClient } from "@/lib/supabase/server";

const EVENT_SELECT =
  "id,title,description,location_text,starts_at,ends_at,source_type,external_event_id,metadata";

export const listEventsInRangeForUser = async (userId: string, fromIso: string, toIso: string) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("events")
    .select(EVENT_SELECT)
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
  return listEventsInRangeForUser(userId, start, nextDayStartInJst(date));
};

export const listEventsForMonthForUser = async (userId: string, month: string) => {
  return listEventsInRangeForUser(userId, startOfMonthInJst(month), nextMonthStartInJst(month));
};

export const searchEventsForUser = async (input: {
  userId: string;
  query: string;
  fromIso?: string;
  toIso?: string;
  limit?: number;
}) => {
  const supabase = await createClient();
  let builder = supabase
    .from("events")
    .select(EVENT_SELECT)
    .eq("user_id", input.userId)
    .neq("status", "cancelled")
    .order("starts_at", { ascending: true })
    .limit(input.limit ?? 10);

  if (input.fromIso) {
    builder = builder.gte("starts_at", input.fromIso);
  }

  if (input.toIso) {
    builder = builder.lt("starts_at", input.toIso);
  }

  const query = input.query.trim();
  if (query) {
    builder = builder.or(
      `title.ilike.%${query}%,location_text.ilike.%${query}%,description.ilike.%${query}%`,
    );
  }

  const { data, error } = await builder;

  if (error) {
    throw new Error(error.message);
  }

  return ((data ?? []) as EventRow[]).map(mapEventRowToEventItem);
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
