import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";
import { getProPriceId, getStripe } from "@/lib/stripe";

const resolveOrigin = (request: Request) =>
  process.env.NEXT_PUBLIC_APP_URL ??
  request.headers.get("origin") ??
  new URL(request.url).origin;

const getOrCreateStripeCustomerId = async (input: {
  userId: string;
  email?: string | null;
}) => {
  const supabase = createAdminClient();
  const { data: existing, error: existingError } = await supabase
    .from("billing_customers")
    .select("stripe_customer_id")
    .eq("user_id", input.userId)
    .maybeSingle();

  if (existingError) {
    throw new Error(existingError.message);
  }

  if (existing?.stripe_customer_id) {
    return existing.stripe_customer_id as string;
  }

  const stripe = getStripe();
  const customer = await stripe.customers.create({
    email: input.email ?? undefined,
    metadata: {
      userId: input.userId,
    },
  });

  const { error: insertError } = await supabase.from("billing_customers").insert({
    user_id: input.userId,
    stripe_customer_id: customer.id,
  });

  if (insertError) {
    throw new Error(insertError.message);
  }

  return customer.id;
};

export async function POST(request: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const origin = resolveOrigin(request);
  const stripe = getStripe();
  const customerId = await getOrCreateStripeCustomerId({
    userId: user.id,
    email: user.email,
  });
  const session = await stripe.checkout.sessions.create({
    mode: "subscription",
    customer: customerId,
    line_items: [
      {
        price: getProPriceId(),
        quantity: 1,
      },
    ],
    success_url: `${origin}/settings?billing=success`,
    cancel_url: `${origin}/settings?billing=cancelled`,
    metadata: {
      userId: user.id,
    },
    subscription_data: {
      metadata: {
        userId: user.id,
      },
    },
  });

  return NextResponse.json({ ok: true, url: session.url });
}
