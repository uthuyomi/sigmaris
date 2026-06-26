// 役割: チャットスレッド一覧の取得や作成を行うNext.js API Route。

import { NextResponse } from "next/server";
import { z } from "zod";
import { createChatThread } from "@/lib/chat-threads";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  threadId: z.uuid().optional(),
});

const getAuthedUser = async () => {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return user;
};

export async function POST(req: Request) {
  const user = await getAuthedUser();
  if (!user) {
    return NextResponse.json({ error: "認証が必要です。" }, { status: 401 });
  }

  const body = await req.json().catch(() => ({}));
  const parsed = requestSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "threadIdが不正です。" }, { status: 400 });
  }

  const thread = await createChatThread(user.id, { id: parsed.data.threadId });
  return NextResponse.json({ ok: true, thread });
}
