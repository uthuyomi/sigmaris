// 役割: 予定に対する移動経路や移動時間を計算するNext.js API Route。

import { NextResponse } from "next/server";
import { z } from "zod";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { fetchBackendJson } from "@/lib/backend/client";

const requestSchema = z.object({
  originType: z.enum(["home", "current", "saved", "custom"]),
  origin: z.string().trim().min(1).max(500),
  destination: z.string().trim().min(1).max(500),
  arrivalTimeIso: z.string().max(64),
  travelMode: z.enum(["bicycle", "car", "walk"]),
});

export async function POST(req: Request) {
  try {
    const authHeaders = await readBackendAuthHeaders();
    const input = requestSchema.parse(await req.json());
    const result = await fetchBackendJson<{ ok: boolean; plan: unknown }>("/api/mobility/plan", {
      method: "POST",
      body: JSON.stringify(input),
      headers: authHeaders,
    });

    return NextResponse.json(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Backend mobility planning failed.";
    const status = message.includes("session") || message.includes("Authentication")
      ? 401
      : message.includes("unavailable")
        ? 503
        : 400;
    return NextResponse.json(
      {
        error: message,
      },
      { status },
    );
  }
}
