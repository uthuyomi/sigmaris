import { NextResponse } from "next/server";
import type Stripe from "stripe";
import { createAdminClient } from "@/lib/supabase/admin";
import { getStripe } from "@/lib/stripe";

export const runtime = "nodejs";

const getSubscriptionPeriodEnd = (subscription: Stripe.Subscription) => {
  const itemPeriodEnd = subscription.items.data[0]?.current_period_end;
  return itemPeriodEnd ? new Date(itemPeriodEnd * 1000).toISOString() : null;
};

const upsertSubscription = async (subscription: Stripe.Subscription) => {
  const userId = subscription.metadata.userId;
  const customerId =
    typeof subscription.customer === "string" ? subscription.customer : subscription.customer.id;

  if (!userId) {
    return;
  }

  const supabase = createAdminClient();
  await supabase.from("billing_customers").upsert(
    {
      user_id: userId,
      stripe_customer_id: customerId,
    },
    { onConflict: "user_id" },
  );

  const { error } = await supabase.from("subscriptions").upsert(
    {
      user_id: userId,
      stripe_customer_id: customerId,
      stripe_subscription_id: subscription.id,
      stripe_price_id: subscription.items.data[0]?.price.id ?? null,
      plan: "pro",
      status: subscription.status,
      current_period_end: getSubscriptionPeriodEnd(subscription),
      cancel_at_period_end: subscription.cancel_at_period_end,
    },
    { onConflict: "stripe_subscription_id" },
  );

  if (error) {
    throw new Error(error.message);
  }
};

export async function POST(request: Request) {
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!webhookSecret) {
    return NextResponse.json({ error: "STRIPE_WEBHOOK_SECRET is not configured." }, { status: 503 });
  }

  const stripe = getStripe();
  const signature = request.headers.get("stripe-signature");
  if (!signature) {
    return NextResponse.json({ error: "Missing Stripe signature." }, { status: 400 });
  }

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(await request.text(), signature, webhookSecret);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Invalid Stripe webhook." },
      { status: 400 },
    );
  }

  if (
    event.type === "customer.subscription.created" ||
    event.type === "customer.subscription.updated" ||
    event.type === "customer.subscription.deleted"
  ) {
    await upsertSubscription(event.data.object);
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object;
    if (typeof session.subscription === "string") {
      const subscription = await stripe.subscriptions.retrieve(session.subscription);
      await upsertSubscription(subscription);
    }
  }

  return NextResponse.json({ received: true });
}
