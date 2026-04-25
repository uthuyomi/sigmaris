// 役割: 優先移動手段の設定を保存するNext.js API Route。

import { NextResponse } from "next/server";
import { z } from "zod";
import { supportedPreferredTravelModes, updatePreferredTravelMode } from "@/lib/profile-settings";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  travelMode: z.enum(supportedPreferredTravelModes),
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
  await updatePreferredTravelMode(user.id, input.travelMode);

  return NextResponse.json({ ok: true, travelMode: input.travelMode });
}
