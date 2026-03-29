import { NextResponse } from "next/server";
import { z } from "zod";
import { readGoogleCalendarSyncEnabled, updateGoogleCalendarSyncEnabled } from "@/lib/profile-settings";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  enabled: z.boolean(),
});

const getAuthedUser = async () => {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return user;
};

export async function GET() {
  const user = await getAuthedUser();
  if (!user) {
    return NextResponse.json({ error: "認証が必要です。" }, { status: 401 });
  }

  return NextResponse.json({
    enabled: await readGoogleCalendarSyncEnabled(user.id),
  });
}

export async function POST(req: Request) {
  const user = await getAuthedUser();
  if (!user) {
    return NextResponse.json({ error: "認証が必要です。" }, { status: 401 });
  }

  const parsed = requestSchema.parse(await req.json());
  await updateGoogleCalendarSyncEnabled(user.id, parsed.enabled);

  return NextResponse.json({
    ok: true,
    enabled: parsed.enabled,
  });
}
