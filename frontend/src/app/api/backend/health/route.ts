// 役割: バックエンドAPIのヘルスチェックを中継するNext.js API Route。

import { NextResponse } from "next/server";
import { readBackendHealth } from "@/lib/backend/health";

export async function GET() {
  const result = await readBackendHealth();
  return NextResponse.json(result, { status: result.ready ? 200 : 503 });
}
