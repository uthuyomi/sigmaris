// 役割: 指定されたチャットスレッドの取得や更新を行うNext.js API Route。

import { NextResponse } from "next/server";
import { z } from "zod";
import { deleteChatThread, renameChatThread } from "@/lib/chat-threads";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  title: z.string().trim().min(1).max(80),
});

const getAuthedUser = async () => {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return user;
};

type RouteContext = {
  params: Promise<{
    threadId: string;
  }>;
};

export async function PATCH(req: Request, context: RouteContext) {
  const user = await getAuthedUser();
  if (!user) {
    return NextResponse.json({ error: "認証が必要です。" }, { status: 401 });
  }

  const { threadId } = await context.params;
  const parsed = requestSchema.parse(await req.json());
  await renameChatThread(user.id, threadId, parsed.title);

  return NextResponse.json({ ok: true });
}

export async function DELETE(_req: Request, context: RouteContext) {
  const user = await getAuthedUser();
  if (!user) {
    return NextResponse.json({ error: "認証が必要です。" }, { status: 401 });
  }

  const { threadId } = await context.params;
  await deleteChatThread(user.id, threadId);

  return NextResponse.json({ ok: true });
}
