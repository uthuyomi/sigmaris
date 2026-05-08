import { NextResponse } from "next/server";
import { buildGoogleMapsDirectionsUrl } from "@/lib/google/maps-url";
import { createClient } from "@/lib/supabase/server";

const DEFAULT_LOOKAHEAD_HOURS = 24;
const MAX_LOOKAHEAD_HOURS = 72;

type TravelBlockMetadata = {
  kind?: string;
  originAddress?: string | null;
  originLabel?: string | null;
  destinationAddress?: string | null;
  destinationLabel?: string | null;
  travelMode?: "bicycle" | "car" | "walk" | null;
  mapsNavigationUrl?: string | null;
};

const parseLookaheadHours = (value: string | null) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return DEFAULT_LOOKAHEAD_HOURS;
  return Math.min(MAX_LOOKAHEAD_HOURS, Math.max(1, Math.round(parsed)));
};

export async function GET(request: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const url = new URL(request.url);
  const lookaheadHours = parseLookaheadHours(url.searchParams.get("lookaheadHours"));
  const now = new Date();
  const to = new Date(now.getTime() + lookaheadHours * 60 * 60 * 1000);

  const { data, error } = await supabase
    .from("events")
    .select("id,title,description,location_text,starts_at,ends_at,metadata")
    .eq("user_id", user.id)
    .neq("status", "cancelled")
    .gte("starts_at", now.toISOString())
    .lt("starts_at", to.toISOString())
    .contains("metadata", { kind: "travel_block" })
    .order("starts_at", { ascending: true })
    .limit(100);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 400 });
  }

  const reminders = (data ?? []).map((event) => {
    const metadata = (event.metadata ?? {}) as TravelBlockMetadata;
    const navigationUrl =
      metadata.mapsNavigationUrl ??
      buildGoogleMapsDirectionsUrl({
        origin: metadata.originAddress,
        destination: metadata.destinationAddress ?? event.location_text,
        travelMode: metadata.travelMode,
      });

    return {
      id: event.id,
      title: event.title,
      description: event.description,
      startsAt: event.starts_at,
      endsAt: event.ends_at,
      originLabel: metadata.originLabel ?? "Origin",
      destinationLabel: metadata.destinationLabel ?? event.location_text ?? "Destination",
      navigationUrl,
    };
  });

  return NextResponse.json({ ok: true, reminders });
}
