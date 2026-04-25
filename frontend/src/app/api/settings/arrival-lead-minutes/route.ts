// 役割: 到着余裕時間の設定を保存するNext.js API Route。

import { NextResponse } from "next/server";
import { z } from "zod";
import { updateArrivalLeadMinutes } from "@/lib/profile-settings";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  minutes: z.number().int().min(0).max(180),
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
  await updateArrivalLeadMinutes(user.id, input.minutes);

  return NextResponse.json({ ok: true, minutes: input.minutes });
}
