import { NextResponse } from "next/server";
import { readGoogleSheetPreview } from "@/lib/google/sheets";
import { extractScheduleFromImage, extractScheduleFromSheetRows } from "@/lib/import/extract";
import { hasOpenAIConfig } from "@/lib/openai/client";

export async function POST(req: Request) {
  if (!hasOpenAIConfig()) {
    return NextResponse.json(
      { error: "OPENAI_API_KEY is not set." },
      { status: 500 },
    );
  }

  const formData = await req.formData();
  const sheetUrl = formData.get("sheetUrl");
  const image = formData.get("image");

  try {
    if (typeof sheetUrl === "string" && sheetUrl.trim()) {
      const preview = await readGoogleSheetPreview(sheetUrl.trim());
      const extracted = await extractScheduleFromSheetRows({
        sheetTitle: preview.sheetTitle,
        rows: preview.rows,
      });

      return NextResponse.json({
        sourceType: "sheet",
        sourceLabel: preview.sheetTitle,
        extracted,
      });
    }

    if (image instanceof File && image.size > 0) {
      const arrayBuffer = await image.arrayBuffer();
      const base64Data = Buffer.from(arrayBuffer).toString("base64");

      const extracted = await extractScheduleFromImage({
        mimeType: image.type || "image/png",
        base64Data,
        filename: image.name,
      });

      return NextResponse.json({
        sourceType: "image",
        sourceLabel: image.name,
        extracted,
      });
    }
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "取り込み処理に失敗しました。" },
      { status: 400 },
    );
  }

  return NextResponse.json(
    { error: "sheetUrl または image を指定してください。" },
    { status: 400 },
  );
}
