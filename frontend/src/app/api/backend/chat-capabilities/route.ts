// Backend chat capability health proxy.
import { NextResponse } from "next/server";
import { readBackendChatCapabilities } from "@/lib/backend/chat";

export async function GET() {
  const result = await readBackendChatCapabilities();
  return NextResponse.json(result, { status: result.ready ? 200 : 503 });
}
