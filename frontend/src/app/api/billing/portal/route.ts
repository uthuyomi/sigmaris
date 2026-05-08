import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";
import { getStripe } from "@/lib/stripe";

const resolveOrigin = (request: Request) =>
  process.env.NEXT_PUBLIC_APP_URL ??
  request.headers.get("origin") ??
  new URL(request.url).origin;

export async function POST(request: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const admin = createAdminClient();
  const { data, error } = await admin
    .from("billing_customers")
    .select("stripe_customer_id")
    .eq("user_id", user.id)
    .maybeSingle();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 400 });
  }

  if (!data?.stripe_customer_id) {
    return NextResponse.json({ error: "Stripe customer was not found." }, { status: 404 });
  }

  const session = await getStripe().billingPortal.sessions.create({
    customer: data.stripe_customer_id as string,
    return_url: `${resolveOrigin(request)}/settings`,
  });

  return NextResponse.json({ ok: true, url: session.url });
}
