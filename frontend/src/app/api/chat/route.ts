// 役割: チャット応答の生成やストリーミングを扱うNext.js API Route。
// Phase A1-b: バックエンドの直接チャットエンドポイント(/api/chat/stream)ではなく
// オーケストレーター(/api/orchestrator/chat/stream)を呼ぶように変更。
// 記憶注入(fact/self_model/trend)とスレッド横断セッション継続(Phase A1)を
// 実際に使われるチャットUIへ反映させるための切り替え。

import type { UIMessage } from "ai";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { getBackendBaseUrl } from "@/lib/backend/client";
import { translateOrchestratorStream } from "@/lib/orchestrator/stream-translator";
import { createClient } from "@/lib/supabase/server";

type IncomingBody = {
  messages?: UIMessage[];
  threadId?: string;
  messageId?: string;
};

const ORCHESTRATOR_MESSAGE_LIMIT = 24;
const ORCHESTRATOR_MESSAGE_TEXT_LIMIT = 20_000;

const extractText = (message: UIMessage): string =>
  message.parts
    .filter((part): part is { type: "text"; text: string } => part.type === "text")
    .map((part) => part.text)
    .join("\n")
    .trim();

const trimMessageText = (text: string): string => {
  if (text.length <= ORCHESTRATOR_MESSAGE_TEXT_LIMIT) return text;
  return text.slice(-ORCHESTRATOR_MESSAGE_TEXT_LIMIT);
};

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
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) {
      throw new Error("Authentication is required.");
    }

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

  const orchestratorMessages = (body.messages ?? [])
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({ role: message.role, content: extractText(message) }))
    .filter((message) => message.content.length > 0)
    .slice(-ORCHESTRATOR_MESSAGE_LIMIT)
    .map((message) => ({ ...message, content: trimMessageText(message.content) }));

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

  return new Response(translateOrchestratorStream(backendResponse.body, body.messageId), {
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
