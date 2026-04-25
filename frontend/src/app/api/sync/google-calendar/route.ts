// 役割: Google Calendarとの同期処理を実行するNext.js API Route。

import { NextResponse } from "next/server";
import { createGoogleCalendarEvents, listGoogleCalendarEvents } from "@/lib/google/calendar";
import { isGoogleInvalidGrantError } from "@/lib/google/oauth";
import { clearGoogleProviderCookies } from "@/lib/google/provider-tokens";
import { createClient } from "@/lib/supabase/server";
import { markGoogleCalendarSyncRun, readGoogleCalendarSyncEnabled } from "@/lib/profile-settings";

const GOOGLE_CALENDAR_WINDOW_YEARS = 2;

const toDateTime = (value?: string | null) => {
  if (!value) return null;
  if (value.includes("T")) return value;
  return `${value}T00:00:00+09:00`;
};

const getSyncRange = () => {
  const now = new Date();
  const from = new Date(now.getFullYear() - GOOGLE_CALENDAR_WINDOW_YEARS, 0, 1);
  const to = new Date(now.getFullYear() + GOOGLE_CALENDAR_WINDOW_YEARS + 1, 0, 1);

  return {
    timeMin: from.toISOString(),
    timeMax: to.toISOString(),
  };
};

export async function POST() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "認証が必要です。" }, { status: 401 });
  }

  const syncEnabled = await readGoogleCalendarSyncEnabled(user.id);
  if (!syncEnabled) {
    return NextResponse.json({ error: "Google カレンダー同期がオフです。" }, { status: 400 });
  }

  const calendarId = process.env.GOOGLE_CALENDAR_ID ?? "primary";

  try {
    const { timeMin, timeMax } = getSyncRange();

    const { data: existingConnection } = await supabase
      .from("calendar_connections")
      .select("id")
      .eq("user_id", user.id)
      .eq("provider", "google")
      .eq("provider_calendar_id", calendarId)
      .maybeSingle();

    let connectionId = existingConnection?.id as string | undefined;

    if (!connectionId) {
      const { data: insertedConnection, error: connectionError } = await supabase
        .from("calendar_connections")
        .insert({
          user_id: user.id,
          provider: "google",
          provider_calendar_id: calendarId,
          display_name: "Google Calendar",
          is_primary: true,
        })
        .select("id")
        .single();

      if (connectionError) {
        throw new Error(connectionError.message);
      }

      connectionId = insertedConnection.id;
    }

    const googleEvents = await listGoogleCalendarEvents({
      calendarId,
      timeMin,
      timeMax,
      maxResults: 2500,
    });

    const { data: appEventsData, error: appEventsError } = await supabase
      .from("events")
      .select(
        "id,title,description,location_text,starts_at,ends_at,source_type,external_event_id,status",
      )
      .eq("user_id", user.id)
      .gte("starts_at", timeMin)
      .lt("starts_at", timeMax);

    if (appEventsError) {
      throw new Error(appEventsError.message);
    }

    const appEvents = appEventsData ?? [];
    const appEventsByExternalId = new Map(
      appEvents
        .filter((event) => event.external_event_id)
        .map((event) => [event.external_event_id as string, event]),
    );

    const googleOnlyEvents = googleEvents.filter((event) => event.id && !appEventsByExternalId.has(event.id));

    if (googleOnlyEvents.length) {
      const insertPayload = googleOnlyEvents
        .map((event) => {
          const startsAt = toDateTime(event.start);
          const endsAt = toDateTime(event.end);
          if (!event.id || !startsAt || !endsAt) return null;

          return {
            user_id: user.id,
            calendar_connection_id: connectionId,
            title: event.summary ?? "Google 予定",
            description: event.description ?? null,
            location_text: event.location ?? null,
            starts_at: startsAt,
            ends_at: endsAt,
            status: event.status === "cancelled" ? "cancelled" : "confirmed",
            source_type: "calendar_sync",
            external_event_id: event.id,
            last_synced_at: new Date().toISOString(),
            metadata: {
              provider: "google",
              htmlLink: event.htmlLink ?? null,
            },
          };
        })
        .filter(Boolean);

      if (insertPayload.length) {
        const { error: insertError } = await supabase.from("events").insert(insertPayload);
        if (insertError) {
          throw new Error(insertError.message);
        }
      }
    }

    const appOnlyEvents = appEvents.filter(
      (event) =>
        !event.external_event_id &&
        event.status !== "cancelled" &&
        event.source_type !== "calendar_sync",
    );

    const appOnlyPayload = appOnlyEvents.map((event) => ({
      title: event.title as string,
      start: event.starts_at as string,
      end: event.ends_at as string,
      description: (event.description as string | null) ?? undefined,
      location: (event.location_text as string | null) ?? undefined,
    }));

    const createdGoogleEvents = appOnlyPayload.length
      ? await createGoogleCalendarEvents(appOnlyPayload, calendarId)
      : [];

    for (let index = 0; index < createdGoogleEvents.length; index += 1) {
      const created = createdGoogleEvents[index];
      const source = appOnlyEvents[index];
      if (!created?.id || !source?.id) continue;

      const { error: updateError } = await supabase
        .from("events")
        .update({
          external_event_id: created.id,
          calendar_connection_id: connectionId,
          last_synced_at: new Date().toISOString(),
        })
        .eq("id", source.id);

      if (updateError) {
        throw new Error(updateError.message);
      }
    }

    await markGoogleCalendarSyncRun(
      user.id,
      `ok: imported=${googleOnlyEvents.length}, exported=${createdGoogleEvents.length}`,
    );

    return NextResponse.json({
      ok: true,
      importedFromGoogle: googleOnlyEvents.length,
      exportedToGoogle: createdGoogleEvents.length,
      timeMin,
      timeMax,
    });
  } catch (error) {
    if (isGoogleInvalidGrantError(error)) {
      await clearGoogleProviderCookies();
      await markGoogleCalendarSyncRun(user.id, "error: google auth expired").catch(() => undefined);

      return NextResponse.json(
        {
          error:
            "Google カレンダーの認証が切れています。一度サインアウトして、Googleでログインし直してください。",
          code: "GOOGLE_AUTH_EXPIRED",
          reconnectRequired: true,
        },
        { status: 401 },
      );
    }

    await markGoogleCalendarSyncRun(
      user.id,
      `error: ${error instanceof Error ? error.message : "sync failed"}`,
    ).catch(() => undefined);

    return NextResponse.json(
      { error: error instanceof Error ? error.message : "同期に失敗しました。" },
      { status: 400 },
    );
  }
}
