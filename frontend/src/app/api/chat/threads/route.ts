// 役割: チャットスレッド一覧の取得や作成を行うNext.js API Route。

import { NextResponse } from "next/server";
import { createChatThread } from "@/lib/chat-threads";
import { createClient } from "@/lib/supabase/server";

const getAuthedUser = async () => {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return user;
};

export async function POST() {
  const user = await getAuthedUser();
  if (!user) {
    return NextResponse.json({ error: "認証が必要です。" }, { status: 401 });
  }

  const thread = await createChatThread(user.id);
  return NextResponse.json({ ok: true, thread });
}
