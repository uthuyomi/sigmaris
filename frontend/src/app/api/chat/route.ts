// 役割: チャット応答の生成やストリーミングを扱うNext.js API Route。

import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { isProBillingStatus, readBillingStatus } from "@/lib/billing";
import { readChatUsageStatus, type ChatUsageStatus } from "@/lib/chat-usage";
import { createClient } from "@/lib/supabase/server";

const createUpgradeStream = (usage: ChatUsageStatus) => {
  const encoder = new TextEncoder();
  const messageId = crypto.randomUUID();
  const textPartId = crypto.randomUUID();
  const message = [
    `Freeプランのチャット上限 ${usage.limit} 回に達したよ。`,
    "",
    "このまま続けるには Settings から ShiftPilotAI Pro にアップグレードしてね。",
    "Proにすると、チャット継続、Google Calendar同期、移動予定、出発前通知、Sheets/画像取り込みが使えるようになるよ。",
  ].join("\n");
  const events = [
    { type: "start", messageId },
    { type: "text-start", id: textPartId },
    { type: "text-delta", id: textPartId, delta: message },
    { type: "text-end", id: textPartId },
    { type: "finish", finishReason: "stop" },
  ];

  return new ReadableStream({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      }
      controller.close();
    },
  });
};

export async function POST(req: Request) {
  const rawBody = await req.text();

  let authHeaders: Record<string, string>;
  let userId: string;
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) {
      throw new Error("Authentication is required.");
    }

    userId = user.id;
    authHeaders = await readBackendAuthHeaders();
  } catch (error) {
    return new Response(
      JSON.stringify({
        error: error instanceof Error ? error.message : "Authentication is required.",
      }),
      {
        status: 401,
        headers: { "Content-Type": "application/json" },
      },
    );
  }

  const [billing, usage] = await Promise.all([
    readBillingStatus(userId),
    readChatUsageStatus(userId),
  ]);
  if (!isProBillingStatus(billing) && usage.limited) {
    return new Response(createUpgradeStream(usage), {
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        "x-vercel-ai-ui-message-stream": "v1",
        "x-shiftpilotai-limit": "free-chat",
      },
    });
  }

  const backendBaseUrl = process.env.BACKEND_API_BASE_URL ?? "http://127.0.0.1:8000";
  const backendResponse = await fetch(`${backendBaseUrl}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
    },
    body: rawBody,
    cache: "no-store",
  });

  if (!backendResponse.body) {
    const text = await backendResponse.text();
    return new Response(text, {
      status: backendResponse.status,
      headers: {
        "Content-Type": backendResponse.headers.get("content-type") ?? "application/json",
      },
    });
  }

  return new Response(backendResponse.body, {
    status: backendResponse.status,
    headers: {
      "content-type": backendResponse.headers.get("content-type") ?? "text/event-stream",
      "cache-control": backendResponse.headers.get("cache-control") ?? "no-cache",
      connection: backendResponse.headers.get("connection") ?? "keep-alive",
      "x-vercel-ai-ui-message-stream":
        backendResponse.headers.get("x-vercel-ai-ui-message-stream") ?? "v1",
      "x-accel-buffering": backendResponse.headers.get("x-accel-buffering") ?? "no",
    },
  });
}
