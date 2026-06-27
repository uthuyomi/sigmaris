import { NextResponse } from "next/server";
import type webpush from "web-push";
import { createClient } from "@/lib/supabase/server";
import { configureWebPush, hasWebPushConfig } from "@/lib/web-push";

export const runtime = "nodejs";

type PushSubscriptionRow = {
  id: string;
  endpoint: string;
  p256dh: string;
  auth: string;
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

export async function POST() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  if (!hasWebPushConfig()) {
    return NextResponse.json(
      { error: "Web Push environment variables are not configured." },
      { status: 503 },
    );
  }

  const { data: subscriptionRows, error } = await supabase
    .from("push_subscriptions")
    .select("id,endpoint,p256dh,auth")
    .eq("user_id", user.id);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 400 });
  }

  const subscriptions = (subscriptionRows ?? []) as PushSubscriptionRow[];
  if (!subscriptions.length) {
    return NextResponse.json({
      ok: true,
      sent: 0,
      subscriptions: 0,
      failedPushes: 0,
      message: "No push subscription is saved for this user.",
    });
  }

  const push = configureWebPush();
  const expiredSubscriptionIds: string[] = [];
  const pushFailures: Array<{ subscriptionId: string; statusCode?: number; message: string }> = [];
  let sent = 0;

  const payload = JSON.stringify({
    title: "Sigmaris test notification",
    body: "Tap to open Google Maps.",
    tag: `push-test:${Date.now()}`,
    navigationUrl: "https://www.google.com/maps",
    reminderId: "push-test",
  });

  for (const subscription of subscriptions) {
    try {
      await push.sendNotification(toPushSubscription(subscription), payload);
      sent += 1;
    } catch (error) {
      if (isExpiredSubscriptionError(error)) {
        expiredSubscriptionIds.push(subscription.id);
      }
      const candidate = error as { statusCode?: number; body?: string; message?: string };
      pushFailures.push({
        subscriptionId: subscription.id,
        statusCode: candidate.statusCode,
        message: candidate.body ?? candidate.message ?? "Web Push send failed.",
      });
    }
  }

  if (expiredSubscriptionIds.length) {
    await supabase.from("push_subscriptions").delete().in("id", expiredSubscriptionIds);
  }

  return NextResponse.json({
    ok: true,
    subscriptions: subscriptions.length,
    sent,
    failedPushes: pushFailures.length,
    expiredSubscriptions: expiredSubscriptionIds.length,
    pushFailures: pushFailures.slice(0, 5),
  });
}
