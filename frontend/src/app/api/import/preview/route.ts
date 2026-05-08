// 役割: シートや画像から予定候補のプレビューを作るNext.js API Route。

import { NextResponse } from "next/server";
import { requireProPlan } from "@/lib/billing-gate";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { createClient } from "@/lib/supabase/server";
import { fetchBackendJson } from "@/lib/backend/client";
import { readGoogleSheetPreview } from "@/lib/google/sheets";

const MAX_IMAGE_BYTES = 8 * 1024 * 1024;

export async function POST(req: Request) {
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const proRequired = await requireProPlan(user.id);
    if (proRequired) return proRequired;

    const authHeaders = await readBackendAuthHeaders();
    const formData = await req.formData();
    const sheetUrl = formData.get("sheetUrl");
    const image = formData.get("image");

    if (typeof sheetUrl === "string" && sheetUrl.trim()) {
      const preview = await readGoogleSheetPreview(sheetUrl.trim());
      const backendResult = await fetchBackendJson<{
        sourceType: "sheet";
        sourceLabel: string;
        extracted: unknown;
      }>("/api/import/preview", {
        method: "POST",
        body: JSON.stringify({
          sourceType: "sheet",
          sourceLabel: preview.sheetTitle,
          sheetTitle: preview.sheetTitle,
          rows: preview.rows,
        }),
        headers: authHeaders,
      });

      return NextResponse.json({
        sourceType: backendResult.sourceType,
        sourceLabel: backendResult.sourceLabel,
        extracted: backendResult.extracted,
      });
    }

    if (image instanceof File && image.size > 0) {
      if (image.size > MAX_IMAGE_BYTES) {
        return NextResponse.json(
          { error: "画像サイズは8MB以下にしてください。" },
          { status: 413 },
        );
      }

      const arrayBuffer = await image.arrayBuffer();
      const base64Data = Buffer.from(arrayBuffer).toString("base64");
      const backendResult = await fetchBackendJson<{
        sourceType: "image";
        sourceLabel: string;
        extracted: unknown;
      }>("/api/import/preview", {
        method: "POST",
        body: JSON.stringify({
          sourceType: "image",
          sourceLabel: image.name,
          filename: image.name,
          mimeType: image.type || "image/png",
          base64Data,
        }),
        headers: authHeaders,
      });

      return NextResponse.json({
        sourceType: backendResult.sourceType,
        sourceLabel: backendResult.sourceLabel,
        extracted: backendResult.extracted,
      });
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "取り込み処理に失敗しました。";
    const status = message.includes("session") || message.includes("Authentication") ? 401 : 400;
    return NextResponse.json(
      { error: message },
      { status },
    );
  }

  return NextResponse.json(
    { error: "sheetUrl または image を指定してください。" },
    { status: 400 },
  );
}
