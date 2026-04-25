// 役割: AI応答トーンの設定を保存するNext.js API Route。

import { NextResponse } from "next/server";
import { z } from "zod";
import { updateAiTone } from "@/lib/profile-settings";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  aiTone: z.enum(["default", "friendly", "concise", "direct"]),
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
  await updateAiTone(user.id, input.aiTone);

  return NextResponse.json({ ok: true, aiTone: input.aiTone });
}
