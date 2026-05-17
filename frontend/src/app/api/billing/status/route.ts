import { NextResponse } from "next/server";
import { readBillingStatus } from "@/lib/billing";
import { createClient } from "@/lib/supabase/server";

export async function GET() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  return NextResponse.json({ ok: true, billing: await readBillingStatus(user.id, user.email) });
}
