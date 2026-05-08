import { NextResponse } from "next/server";
import type webpush from "web-push";
import { buildGoogleMapsDirectionsUrl } from "@/lib/google/maps-url";
import { createAdminClient } from "@/lib/supabase/admin";
import { configureWebPush } from "@/lib/web-push";

export const runtime = "nodejs";

const REMINDER_LEAD_MINUTES = 5;
const LOOKAHEAD_MINUTES = 6;

type TravelBlockMetadata = {
  kind?: string;
  originAddress?: string | null;
  originLabel?: string | null;
  destinationAddress?: string | null;
  destinationLabel?: string | null;
  travelMode?: "bicycle" | "car" | "walk" | null;
  mapsNavigationUrl?: string | null;
};

type EventRow = {
  id: string;
  user_id: string;
  title: string;
  description: string | null;
  location_text: string | null;
  starts_at: string;
  ends_at: string;
  metadata: TravelBlockMetadata | null;
};

type PushSubscriptionRow = {
  id: string;
  user_id: string;
  endpoint: string;
  p256dh: string;
  auth: string;
};

const isAuthorized = (request: Request) => {
  const secret = process.env.CRON_SECRET;
  if (!secret) return process.env.NODE_ENV !== "production";
  return request.headers.get("authorization") === `Bearer ${secret}`;
};

const toPushSubscription = (row: PushSubscriptionRow): webpush.PushSubscription => ({
  endpoint: row.endpoint,
  keys: {
    p256dh: row.p256dh,
    auth: row.auth,
  },
});

const isExpiredSubscriptionError = (error: unknown) => {
  const candidate = error as { statusCode?: number };
  return candidate.statusCode === 404 || candidate.statusCode === 410;
};

const formatStartTime = (value: string) =>
  new Intl.DateTimeFormat("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Tokyo",
  }).format(new Date(value));

export async function POST(request: Request) {
  if (!isAuthorized(request)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const supabase = createAdminClient();
  const push = configureWebPush();
  const now = new Date();
  const to = new Date(now.getTime() + LOOKAHEAD_MINUTES * 60_000);

  const { data: eventRows, error: eventsError } = await supabase
    .from("events")
    .select("id,user_id,title,description,location_text,starts_at,ends_at,metadata")
    .neq("status", "cancelled")
    .gte("starts_at", now.toISOString())
    .lte("starts_at", to.toISOString())
    .contains("metadata", { kind: "travel_block" })
    .order("starts_at", { ascending: true })
    .limit(200);

  if (eventsError) {
    return NextResponse.json({ error: eventsError.message }, { status: 400 });
  }

  const events = (eventRows ?? []) as EventRow[];
  if (!events.length) {
    return NextResponse.json({ ok: true, sent: 0, events: 0 });
  }

  const eventIds = events.map((event) => event.id);
  const { data: deliveredRows, error: deliveredError } = await supabase
    .from("travel_notification_deliveries")
    .select("event_id,scheduled_for")
    .in("event_id", eventIds)
    .eq("notification_kind", "departure_reminder");

  if (deliveredError) {
    return NextResponse.json({ error: deliveredError.message }, { status: 400 });
  }

  const deliveredKeys = new Set(
    (deliveredRows ?? []).map((row) => `${row.event_id}:${new Date(row.scheduled_for).toISOString()}`),
  );
  const dueEvents = events.filter(
    (event) => !deliveredKeys.has(`${event.id}:${new Date(event.starts_at).toISOString()}`),
  );

  if (!dueEvents.length) {
    return NextResponse.json({ ok: true, sent: 0, events: 0 });
  }

  const userIds = [...new Set(dueEvents.map((event) => event.user_id))];
  const { data: subscriptionRows, error: subscriptionsError } = await supabase
    .from("push_subscriptions")
    .select("id,user_id,endpoint,p256dh,auth")
    .in("user_id", userIds);

  if (subscriptionsError) {
    return NextResponse.json({ error: subscriptionsError.message }, { status: 400 });
  }

  const subscriptionsByUser = new Map<string, PushSubscriptionRow[]>();
  for (const subscription of (subscriptionRows ?? []) as PushSubscriptionRow[]) {
    subscriptionsByUser.set(subscription.user_id, [
      ...(subscriptionsByUser.get(subscription.user_id) ?? []),
      subscription,
    ]);
  }

  let sent = 0;
  const expiredSubscriptionIds: string[] = [];
  const deliveredPayload = [];

  for (const event of dueEvents) {
    const metadata = event.metadata ?? {};
    const navigationUrl =
      metadata.mapsNavigationUrl ??
      buildGoogleMapsDirectionsUrl({
        origin: metadata.originAddress,
        destination: metadata.destinationAddress ?? event.location_text,
        travelMode: metadata.travelMode,
      });
    const subscriptions = subscriptionsByUser.get(event.user_id) ?? [];
    if (!subscriptions.length) continue;

    const payload = JSON.stringify({
      title: `Leave in ${REMINDER_LEAD_MINUTES} min: ${metadata.destinationLabel ?? event.title}`,
      body: `${formatStartTime(event.starts_at)} departure. Tap to open Google Maps.`,
      tag: `${event.id}:${event.starts_at}`,
      navigationUrl,
      reminderId: event.id,
    });

    let eventSent = false;
    for (const subscription of subscriptions) {
      try {
        await push.sendNotification(toPushSubscription(subscription), payload);
        sent += 1;
        eventSent = true;
      } catch (error) {
        if (isExpiredSubscriptionError(error)) {
          expiredSubscriptionIds.push(subscription.id);
        }
      }
    }

    if (eventSent) {
      deliveredPayload.push({
        user_id: event.user_id,
        event_id: event.id,
        notification_kind: "departure_reminder",
        scheduled_for: event.starts_at,
      });
    }
  }

  if (deliveredPayload.length) {
    await supabase.from("travel_notification_deliveries").upsert(deliveredPayload, {
      onConflict: "user_id,event_id,notification_kind,scheduled_for",
    });
  }

  if (expiredSubscriptionIds.length) {
    await supabase.from("push_subscriptions").delete().in("id", expiredSubscriptionIds);
  }

  return NextResponse.json({
    ok: true,
    events: dueEvents.length,
    sent,
    expiredSubscriptions: expiredSubscriptionIds.length,
  });
}

export const GET = POST;
