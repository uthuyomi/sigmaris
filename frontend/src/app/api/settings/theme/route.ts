// Saves the user's app theme preference.
import { NextResponse } from "next/server";
import { z } from "zod";
import { updateAppTheme } from "@/lib/profile-settings";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  theme: z.enum(["light", "dark"]),
});

export async function POST(request: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const input = requestSchema.parse(await request.json());
  await updateAppTheme(user.id, input.theme);

  return NextResponse.json({ ok: true, theme: input.theme });
}
