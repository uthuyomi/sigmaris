// 役割: チャット応答の生成やストリーミングを扱うNext.js API Route。
// Phase A1-b: バックエンドの直接チャットエンドポイント(/api/chat/stream)ではなく
// オーケストレーター(/api/orchestrator/chat/stream)を呼ぶように変更。
// 記憶注入(fact/self_model/trend)とスレッド横断セッション継続(Phase A1)を
// 実際に使われるチャットUIへ反映させるための切り替え。

import type { UIMessage } from "ai";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { getBackendBaseUrl } from "@/lib/backend/client";
import { isProBillingStatus, readBillingStatus } from "@/lib/billing";
import { readChatUsageStatus, type ChatUsageStatus } from "@/lib/chat-usage";
import { translateOrchestratorStream } from "@/lib/orchestrator/stream-translator";
import { PRO_MONTHLY_PRICE_JPY } from "@/lib/stripe";
import { createClient } from "@/lib/supabase/server";

const createUpgradeStream = (usage: ChatUsageStatus) => {
  const encoder = new TextEncoder();
  const messageId = crypto.randomUUID();
  const textPartId = crypto.randomUUID();
  const price = PRO_MONTHLY_PRICE_JPY.toLocaleString("ja-JP");
  const message = [
    `無料チャット上限 ${usage.limit} 回に達しました。`,
    "",
    `このまま続ける場合は、シグマリス Proが月額${price}円です。`,
    "Settings の Proプランから手続きできます。",
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

type IncomingBody = {
  messages?: UIMessage[];
  threadId?: string;
};

const extractText = (message: UIMessage): string =>
  message.parts
    .filter((part): part is { type: "text"; text: string } => part.type === "text")
    .map((part) => part.text)
    .join("\n")
    .trim();

export async function POST(req: Request) {
  const rawBody = await req.text();

  let body: IncomingBody;
  try {
    body = JSON.parse(rawBody) as IncomingBody;
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON body." }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  let authHeaders: Record<string, string>;
  let userId: string;
  let userEmail: string | null | undefined;
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) {
      throw new Error("Authentication is required.");
    }

    userId = user.id;
    userEmail = user.email;
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
    readBillingStatus(userId, userEmail),
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

  const orchestratorMessages = (body.messages ?? [])
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({ role: message.role, content: extractText(message) }))
    .filter((message) => message.content.length > 0);

  if (orchestratorMessages.length === 0) {
    return new Response(JSON.stringify({ error: "messages is required." }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const backendResponse = await fetch(`${getBackendBaseUrl()}/api/orchestrator/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
    },
    body: JSON.stringify({
      messages: orchestratorMessages,
      thread_id: body.threadId,
      context: { reason: "User submitted a message through the Sigmaris /chat web interface." },
    }),
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

  return new Response(translateOrchestratorStream(backendResponse.body), {
    status: backendResponse.status,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      connection: "keep-alive",
      "x-vercel-ai-ui-message-stream": "v1",
      "x-accel-buffering": "no",
    },
  });
}
