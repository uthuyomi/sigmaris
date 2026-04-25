// 役割: 予定データをSupabaseのDBへ書き込む処理をまとめる。

import { createClient } from "@/lib/supabase/server";

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
