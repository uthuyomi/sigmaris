// 役割: 予定データをSupabaseのDBへ書き込む処理をまとめる。

import { createClient } from "@/lib/supabase/server";

const EVENT_SELECT_COLUMNS =
  "id,user_id,title,description,location_text,starts_at,ends_at,source_type,external_event_id,status,calendar_connection_id,metadata";

type EventWriteInput = {
  title: string;
  description?: string | null;
  locationText?: string | null;
  startsAt: string;
  endsAt: string;
  sourceType?: "manual" | "chat" | "sheet" | "image" | "calendar_sync";
  externalEventId?: string | null;
  calendarConnectionId?: string | null;
  metadata?: Record<string, unknown>;
};

const normalizeEventTime = (value: string) => new Date(value).toISOString();

const eventMatchKey = (event: { title: string; starts_at?: string; ends_at?: string; startsAt?: string; endsAt?: string }) =>
  [
    event.title.trim(),
    normalizeEventTime(event.starts_at ?? event.startsAt ?? ""),
    normalizeEventTime(event.ends_at ?? event.endsAt ?? ""),
  ].join("\u0000");

const compactRows = <T>(rows: Array<T | null>): T[] => rows.filter((row): row is T => row !== null);

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

export const createEventsForUser = async (
  userId: string,
  events: EventWriteInput[],
) => {
  if (!events.length) return [];

  const supabase = await createClient();
  const sortedStarts = events.map((event) => event.startsAt).sort();
  const sortedEnds = events.map((event) => event.endsAt).sort();
  const { data: existingRows, error: existingError } = await supabase
    .from("events")
    .select(EVENT_SELECT_COLUMNS)
    .eq("user_id", userId)
    .neq("status", "cancelled")
    .gte("starts_at", sortedStarts[0])
    .lte("ends_at", sortedEnds[sortedEnds.length - 1])
    .limit(1000);

  if (existingError) {
    throw new Error(existingError.message);
  }

  const existingByKey = new Map<string, NonNullable<typeof existingRows>[number]>();
  for (const row of existingRows ?? []) {
    if (row.starts_at && row.ends_at) {
      existingByKey.set(eventMatchKey(row), row);
    }
  }

  const orderedResults: Array<NonNullable<typeof existingRows>[number] | null> = new Array(events.length).fill(null);
  const eventsToInsert: Array<{ index: number; event: EventWriteInput }> = [];
  events.forEach((event, index) => {
    const existing = existingByKey.get(eventMatchKey(event));
    if (existing) {
      orderedResults[index] = existing;
      return;
    }
    eventsToInsert.push({ index, event });
  });

  if (!eventsToInsert.length) {
    return compactRows(orderedResults);
  }

  const { data, error } = await supabase
    .from("events")
    .insert(
      eventsToInsert.map(({ event }) => ({
        user_id: userId,
        title: event.title,
        description: event.description ?? null,
        location_text: event.locationText ?? null,
        starts_at: event.startsAt,
        ends_at: event.endsAt,
        source_type: event.sourceType ?? "manual",
        external_event_id: event.externalEventId ?? null,
        calendar_connection_id: event.calendarConnectionId ?? null,
        metadata: event.metadata ?? {},
      })),
    )
    .select(EVENT_SELECT_COLUMNS);

  if (error) {
    throw new Error(error.message);
  }

  eventsToInsert.forEach(({ index }, createdIndex) => {
    orderedResults[index] = data?.[createdIndex] ?? null;
  });

  return compactRows(orderedResults);
};

export const updateEventExternalLinkForUser = async (input: {
  eventId: string;
  externalEventId?: string | null;
  calendarConnectionId?: string | null;
  metadata?: Record<string, unknown>;
}) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("events")
    .update({
      external_event_id: input.externalEventId ?? null,
      calendar_connection_id: input.calendarConnectionId ?? null,
      metadata: input.metadata ?? {},
    })
    .eq("id", input.eventId)
    .select(
      "id,user_id,title,description,location_text,starts_at,ends_at,source_type,external_event_id,status,calendar_connection_id,metadata",
    )
    .maybeSingle();

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
  travelMode: "bicycle" | "car" | "walk";
  recommendedDepartureAt?: string;
  estimatedArrivalAt?: string;
  durationMinutes?: number;
  routeSummary?: string;
  routeSteps: unknown[];
  fareText?: string;
  fareAmount?: number;
  fareCurrency?: string;
  transferCount?: number;
  walkingDistanceMeters?: number;
  walkingDurationMinutes?: number;
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
    fare_text: input.fareText ?? null,
    fare_amount: input.fareAmount ?? null,
    fare_currency: input.fareCurrency ?? null,
    transfer_count: input.transferCount ?? null,
    walking_distance_meters: input.walkingDistanceMeters ?? null,
    walking_duration_minutes: input.walkingDurationMinutes ?? null,
  });

  if (error) {
    throw new Error(error.message);
  }
};
