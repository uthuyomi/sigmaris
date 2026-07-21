// 役割: プレビュー済み予定候補をアプリDBと外部カレンダーへ保存するNext.js API Route。
import { NextResponse } from "next/server";
import { z } from "zod";
import { createEventsForUser, updateEventExternalLinkForUser } from "@/lib/event-data/writes";
import { createGoogleCalendarEvents } from "@/lib/google/calendar";
import { importCandidateSchema } from "@/lib/import/schema";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  target: z.enum(["google-calendar", "app-calendar"]),
  candidates: z.array(importCandidateSchema).max(100),
  sourceType: z.enum(["sheet", "image"]).optional(),
});

const toIsoDateTime = (date: string, time: string) => `${date}T${time}:00+09:00`;

type ImportedSourceType = "sheet" | "image";
type CreatedGoogleEvents = Awaited<ReturnType<typeof createGoogleCalendarEvents>>;

const getOrCreateGoogleConnectionId = async (userId: string) => {
  const supabase = await createClient();
  const calendarId = process.env.GOOGLE_CALENDAR_ID ?? "primary";
  const { data: existingConnection, error: existingError } = await supabase
    .from("calendar_connections")
    .select("id")
    .eq("user_id", userId)
    .eq("provider", "google")
    .eq("provider_calendar_id", calendarId)
    .maybeSingle();

  if (existingError) {
    throw new Error(existingError.message);
  }

  if (existingConnection?.id) {
    return existingConnection.id as string;
  }

  const { data: insertedConnection, error: insertError } = await supabase
    .from("calendar_connections")
    .insert({
      user_id: userId,
      provider: "google",
      provider_calendar_id: calendarId,
      display_name: "Google Calendar",
      is_primary: true,
    })
    .select("id")
    .single();

  if (insertError) {
    throw new Error(insertError.message);
  }

  return insertedConnection.id as string;
};

const saveCandidatesToAppCalendar = async (
  userId: string,
  candidates: z.infer<typeof importCandidateSchema>[],
  options?: {
    sourceType?: ImportedSourceType;
    createdGoogleEvents?: CreatedGoogleEvents;
    calendarConnectionId?: string | null;
  },
) => {
  const sourceType = options?.sourceType ?? "sheet";
  return createEventsForUser(
    userId,
    candidates.map((candidate, index) => {
      const googleEvent = options?.createdGoogleEvents?.[index];
      return {
        title: candidate.title,
        description: candidate.description,
        startsAt: toIsoDateTime(candidate.date, candidate.startTime),
        endsAt: toIsoDateTime(candidate.date, candidate.endTime),
        sourceType,
        externalEventId: googleEvent?.id ?? null,
        calendarConnectionId: options?.calendarConnectionId ?? null,
        metadata: {
          importedFrom: sourceType,
          googleHtmlLink: googleEvent?.htmlLink ?? null,
        },
      };
    }),
  );
};

export async function POST(req: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const parsed = requestSchema.parse(await req.json());

  if (parsed.target === "app-calendar") {
    const createdAppEvents = await saveCandidatesToAppCalendar(user.id, parsed.candidates, {
      sourceType: parsed.sourceType,
    });

    return NextResponse.json({
      ok: true,
      target: parsed.target,
      createdCount: createdAppEvents.length,
      createdAppEvents,
    });
  }

  try {
    const calendarConnectionId = await getOrCreateGoogleConnectionId(user.id);
    const createdAppEvents = await saveCandidatesToAppCalendar(user.id, parsed.candidates, {
      sourceType: parsed.sourceType,
      calendarConnectionId,
    });
    const googleCreateTargets = parsed.candidates
      .map((candidate, index) => ({ candidate, appEvent: createdAppEvents[index] }))
      .filter(
        (
          target,
        ): target is typeof target & { appEvent: NonNullable<(typeof createdAppEvents)[number]> } =>
          Boolean(target.appEvent && !target.appEvent.external_event_id),
      );
    const created = await createGoogleCalendarEvents(
      googleCreateTargets.map(({ candidate }) => ({
        title: candidate.title,
        start: toIsoDateTime(candidate.date, candidate.startTime),
        end: toIsoDateTime(candidate.date, candidate.endTime),
        description: candidate.description ?? undefined,
      })),
    );
    await Promise.all(
      googleCreateTargets.map(({ appEvent }, index) => {
        const googleEvent = created[index];
        return updateEventExternalLinkForUser({
          eventId: appEvent.id,
          externalEventId: googleEvent?.id ?? null,
          calendarConnectionId,
          metadata: {
            importedFrom: parsed.sourceType ?? "sheet",
            googleHtmlLink: googleEvent?.htmlLink ?? null,
            syncStatus: googleEvent?.id ? "synced" : "pending",
          },
        });
      }),
    );

    return NextResponse.json({
      ok: true,
      target: parsed.target,
      createdCount: created.length,
      created,
      appCreatedCount: createdAppEvents.length,
      skippedExistingGoogleCount: parsed.candidates.length - googleCreateTargets.length,
      createdAppEvents,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Google Calendar sync failed." },
      { status: 400 },
    );
  }
}
