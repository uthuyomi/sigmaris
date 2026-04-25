// 役割: チャット応答の生成やストリーミングを扱うNext.js API Route。

import { readBackendAuthHeaders } from "@/lib/backend/auth";

export async function POST(req: Request) {
  const rawBody = await req.text();

  let authHeaders: Record<string, string>;
  try {
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
