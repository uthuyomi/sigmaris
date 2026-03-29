import { NextResponse } from "next/server";
import { supportedLocales } from "@/lib/i18n";
import { readUserLocale, updateUserLocale } from "@/lib/profile-settings";
import { createClient } from "@/lib/supabase/server";

export async function GET() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const locale = await readUserLocale(user.id);
  return NextResponse.json({ locale, supportedLocales });
}

export async function POST(request: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = (await request.json().catch(() => null)) as { locale?: string } | null;
  if (!body?.locale || !supportedLocales.includes(body.locale as (typeof supportedLocales)[number])) {
    return NextResponse.json({ error: "Unsupported locale" }, { status: 400 });
  }

  await updateUserLocale(user.id, body.locale);
  return NextResponse.json({ locale: body.locale });
}
