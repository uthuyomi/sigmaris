import { NextResponse } from "next/server";
import { z } from "zod";
import { createGoogleCalendarEvents, hasGoogleCalendarWriteConfig } from "@/lib/google/calendar";
import {
  createEventForUser,
  getEventRowByIdForUser,
  listConflictingEventsForUser,
  replaceTravelPlanForEvent,
} from "@/lib/events";
import { getSimpleRoutePlan, getTransitRoutePlan } from "@/lib/google/maps";
import { readGoogleCalendarSyncEnabled } from "@/lib/profile-settings";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  eventId: z.string().uuid(),
  originType: z.enum(["home", "current", "saved", "custom"]),
  origin: z.string().min(1),
  originLabel: z.string().min(1),
  travelMode: z.enum(["transit", "driving", "walking"]),
  confirm: z.boolean().optional(),
  force: z.boolean().optional(),
});

const toTimeLabel = (iso: string) =>
  new Intl.DateTimeFormat("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Tokyo",
  }).format(new Date(iso));

export async function POST(request: Request) {
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const input = requestSchema.parse(await request.json());
    const event = await getEventRowByIdForUser(user.id, input.eventId);

    if (!event) {
      return NextResponse.json({ error: "Event not found." }, { status: 404 });
    }

    if (!event.location_text) {
      return NextResponse.json({ error: "The selected event has no destination." }, { status: 400 });
    }

    const plan =
      input.travelMode === "transit"
        ? await getTransitRoutePlan({
            origin: input.origin,
            destination: event.location_text,
            arrivalTimeIso: event.starts_at,
          })
        : await getSimpleRoutePlan({
            origin: input.origin,
            destination: event.location_text,
            arrivalTimeIso: event.starts_at,
            mode: input.travelMode,
          });

    if (!plan.recommendedDepartureIso) {
      return NextResponse.json({ error: "Could not calculate a departure time." }, { status: 400 });
    }

    const conflicts = await listConflictingEventsForUser({
      userId: user.id,
      startsAt: plan.recommendedDepartureIso,
      endsAt: event.starts_at,
      excludeEventIds: [event.id],
    });

    const warnings = conflicts.map((conflict) => ({
      id: conflict.id,
      title: conflict.title,
      startsAt: conflict.starts_at,
      endsAt: conflict.ends_at,
      location: conflict.location_text,
    }));

    const travelEventDraft = {
      title: `Travel: ${input.originLabel} -> ${event.title}`,
      description: `${input.travelMode} / ${plan.durationText ?? ""}`.trim(),
      locationText: event.location_text,
      startsAt: plan.recommendedDepartureIso,
      endsAt: event.starts_at,
    };

    const syncEnabled =
      hasGoogleCalendarWriteConfig() && (await readGoogleCalendarSyncEnabled(user.id).catch(() => false));

    if (!input.confirm) {
      return NextResponse.json({
        ok: true,
        preview: true,
        routePlan: plan,
        travelEvent: travelEventDraft,
        warnings,
        willSyncToGoogle: syncEnabled,
      });
    }

    if (warnings.length && !input.force) {
      return NextResponse.json(
        {
          error: "Conflicts detected.",
          warnings,
          travelEvent: travelEventDraft,
          routePlan: plan,
        },
        { status: 409 },
      );
    }

    let externalEventId: string | null = null;
    if (syncEnabled) {
      const created = await createGoogleCalendarEvents([
        {
          title: travelEventDraft.title,
          start: travelEventDraft.startsAt,
          end: travelEventDraft.endsAt,
          description: travelEventDraft.description,
          location: travelEventDraft.locationText ?? undefined,
        },
      ]);
      externalEventId = created[0]?.id ?? null;
    }

    const createdEvent = await createEventForUser({
      userId: user.id,
      title: travelEventDraft.title,
      description: travelEventDraft.description,
      locationText: travelEventDraft.locationText,
      startsAt: travelEventDraft.startsAt,
      endsAt: travelEventDraft.endsAt,
      sourceType: "manual",
      externalEventId,
      metadata: {
        kind: "travel_block",
        linkedEventId: event.id,
        originType: input.originType,
        originLabel: input.originLabel,
        destinationLabel: event.title,
        travelMode: input.travelMode,
      },
    });

    await replaceTravelPlanForEvent({
      eventId: event.id,
      originLabel: input.originLabel,
      originAddress: input.origin,
      destinationLabel: event.title,
      destinationAddress: event.location_text,
      travelMode: input.travelMode,
      recommendedDepartureAt: plan.recommendedDepartureIso,
      estimatedArrivalAt: event.starts_at,
      durationMinutes: plan.durationSeconds ? Math.ceil(plan.durationSeconds / 60) : undefined,
      routeSummary: `${toTimeLabel(plan.recommendedDepartureIso)} -> ${toTimeLabel(event.starts_at)}`,
      routeSteps: plan.steps,
    });

    return NextResponse.json({
      ok: true,
      preview: false,
      routePlan: plan,
      warnings,
      createdEvent,
      savedToGoogle: Boolean(externalEventId),
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Mobility scheduling failed.";
    console.error("[mobility/schedule]", error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
