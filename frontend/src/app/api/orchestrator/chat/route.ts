import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { createClient } from "@/lib/supabase/server";

type RequestBody = {
  messages?: Array<{ role?: string; content?: string }>;
  threadId?: string;
};

export async function POST(request: Request) {
  let body: RequestBody;
  try {
    body = (await request.json()) as RequestBody;
  } catch {
    return Response.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  if (!Array.isArray(body.messages) || body.messages.length === 0) {
    return Response.json({ error: "messages is required." }, { status: 400 });
  }

  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) {
      return Response.json({ error: "Authentication is required." }, { status: 401 });
    }

    const authHeaders = await readBackendAuthHeaders();
    const backendBaseUrl =
      process.env.BACKEND_API_BASE_URL ?? "http://127.0.0.1:8000";
    const backendResponse = await fetch(
      `${backendBaseUrl}/api/orchestrator/chat`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,
        },
        body: JSON.stringify({
          messages: body.messages,
          thread_id: body.threadId,
          context: {
            reason: "User submitted a message through the Sigmaris web interface.",
          },
        }),
        cache: "no-store",
      },
    );

    const text = await backendResponse.text();
    return new Response(text, {
      status: backendResponse.status,
      headers: {
        "Content-Type":
          backendResponse.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (error) {
    return Response.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Sigmaris orchestrator request failed.",
      },
      { status: 500 },
    );
  }
}
