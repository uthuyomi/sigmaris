import { NextResponse } from "next/server";
import { clearGoogleProviderCookies } from "@/lib/google/provider-tokens";
import { createClient } from "@/lib/supabase/server";

export async function POST() {
  const supabase = await createClient();
  await supabase.auth.signOut();
  await clearGoogleProviderCookies();

  return NextResponse.json({ ok: true });
}
