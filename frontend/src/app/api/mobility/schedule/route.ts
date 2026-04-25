// 役割: 移動計画で使う予定一覧を返すNext.js API Route。

import { NextResponse } from "next/server";
import { z } from "zod";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { createGoogleCalendarEvents, hasGoogleCalendarWriteConfig } from "@/lib/google/calendar";
import { getBackendBaseUrl } from "@/lib/backend/client";
import {
  createEventForUser,
  getEventRowByIdForUser,
  listConflictingEventsForUser,
  replaceTravelPlanForEvent,
} from "@/lib/events";
import { readArrivalLeadMinutes, readGoogleCalendarSyncEnabled } from "@/lib/profile-settings";
import { createClient } from "@/lib/supabase/server";

type SupportedTravelMode = "bicycle" | "car" | "walk";

const requestSchema = z.object({
  eventId: z.string().uuid(),
  originType: z.enum(["home", "current", "saved", "custom"]),
  origin: z.string().min(1),
  originLabel: z.string().min(1),
  travelMode: z.enum(["bicycle", "car", "walk"]),
  confirm: z.boolean().optional(),
  force: z.boolean().optional(),
});

type BackendPlan = {
  mode: SupportedTravelMode;
  originLabel: string;
  destinationLabel: string;
  recommendedDepartureTime?: string;
  recommendedDepartureIso?: string;
  estimatedArrivalTime?: string;
  estimatedArrivalIso?: string;
  durationText?: string;
  durationSeconds?: number;
  walkingDurationText?: string;
  walkingDurationSeconds?: number;
  walkingDistanceText?: string;
  walkingDistanceMeters?: number;
  transferCount?: number;
  fareText?: string;
  fareAmount?: number;
  fareCurrency?: string;
  routeSummary?: string;
  steps: unknown[];
};

type BackendPayload = {
  ok?: boolean;
  plan?: BackendPlan;
  reason?: string;
  status?: string;
  resolution?: unknown;
  detail?: {
    error?: string;
    routeLookup?: {
      status?: string;
      resolution?: unknown;
    };
  };
};

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
    const arrivalLeadMinutes = await readArrivalLeadMinutes(user.id);

    if (!event) {
      return NextResponse.json({ error: "Event not found." }, { status: 404 });
    }

    if (!event.location_text) {
      return NextResponse.json({ error: "The selected event has no destination." }, { status: 400 });
    }

    const desiredArrivalDate = new Date(event.starts_at);
    desiredArrivalDate.setUTCMinutes(desiredArrivalDate.getUTCMinutes() - arrivalLeadMinutes);
    const desiredArrivalIso = desiredArrivalDate.toISOString();

    const backendBaseUrl = getBackendBaseUrl();
    const authHeaders = await readBackendAuthHeaders();
    let routePlanResponse: Response;
    try {
      routePlanResponse = await fetch(`${backendBaseUrl}/api/mobility/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({
          originType: input.originType,
          origin: input.origin,
          destination: event.location_text,
          arrivalTimeIso: desiredArrivalIso,
          travelMode: input.travelMode,
        }),
        cache: "no-store",
      });
    } catch {
      return NextResponse.json(
        {
          error: `Backend mobility API is unavailable at ${backendBaseUrl}. Start it with: cd backend; python -m uvicorn app.main:app --reload --port 8000`,
        },
        { status: 503 },
      );
    }

    const backendPayload = (await routePlanResponse.json()) as BackendPayload;
    const plan = backendPayload.plan;

    if (!routePlanResponse.ok || !plan) {
      return NextResponse.json(
        {
          error:
            backendPayload.detail?.error ??
            backendPayload.reason ??
            "Backend mobility planning failed.",
          routeLookup: backendPayload.detail?.routeLookup ?? {
            status: backendPayload.status,
            resolution: backendPayload.resolution,
          },
        },
        { status: routePlanResponse.status || 500 },
      );
    }

    if (!plan.recommendedDepartureIso) {
      return NextResponse.json({ error: "Could not calculate a departure time." }, { status: 400 });
    }
    const travelBlockEndIso = plan.estimatedArrivalIso ?? desiredArrivalIso;

    const conflicts = await listConflictingEventsForUser({
      userId: user.id,
      startsAt: plan.recommendedDepartureIso,
      endsAt: travelBlockEndIso,
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
      endsAt: travelBlockEndIso,
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
        arrivalLeadMinutes,
        desiredArrivalIso,
      });
    }

    if (warnings.length && !input.force) {
      return NextResponse.json(
        {
          error: "Conflicts detected.",
          warnings,
          travelEvent: travelEventDraft,
          routePlan: plan,
          arrivalLeadMinutes,
          desiredArrivalIso,
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
      estimatedArrivalAt: plan.estimatedArrivalIso ?? desiredArrivalIso,
      durationMinutes: plan.durationSeconds ? Math.ceil(plan.durationSeconds / 60) : undefined,
      routeSummary:
        plan.routeSummary ??
        `${toTimeLabel(plan.recommendedDepartureIso)} -> ${toTimeLabel(travelBlockEndIso)}`,
      routeSteps: plan.steps,
      fareText: plan.fareText,
      fareAmount: plan.fareAmount,
      fareCurrency: plan.fareCurrency,
      transferCount: plan.transferCount,
      walkingDistanceMeters: plan.walkingDistanceMeters,
      walkingDurationMinutes: plan.walkingDurationSeconds
        ? Math.ceil(plan.walkingDurationSeconds / 60)
        : undefined,
    });

    return NextResponse.json({
      ok: true,
      preview: false,
      routePlan: plan,
      warnings,
      createdEvent,
      savedToGoogle: Boolean(externalEventId),
      arrivalLeadMinutes,
      desiredArrivalIso,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Mobility scheduling failed.";
    console.error("[mobility/schedule]", error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
