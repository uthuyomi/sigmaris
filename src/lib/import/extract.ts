import { zodTextFormat } from "openai/helpers/zod";
import { getOpenAIClient } from "@/lib/openai/client";
import { importPreviewSchema } from "@/lib/import/schema";

const promptBase = [
  "あなたは勤務表や出勤情報を予定候補へ変換する抽出エンジンです。",
  "必ず日本時間を前提に解釈してください。",
  "出力は schedule_import_preview スキーマに従ってください。",
  "分からない項目は推測しすぎず、summary に曖昧さを書いてください。",
  "候補は開始時刻と終了時刻を HH:mm 形式で返してください。",
].join("\n");

export const extractScheduleFromSheetRows = async (input: {
  sheetTitle: string;
  rows: string[][];
}) => {
  const client = getOpenAIClient();

  const response = await client.responses.parse({
    model: process.env.OPENAI_IMPORT_MODEL ?? process.env.OPENAI_MODEL ?? "gpt-5-nano",
    input: [
      {
        role: "system",
        content: [{ type: "input_text", text: promptBase }],
      },
      {
        role: "user",
        content: [
          {
            type: "input_text",
            text: [
              `シート名: ${input.sheetTitle}`,
              "以下の表データから勤務情報を抽出してください。",
              JSON.stringify(input.rows),
            ].join("\n\n"),
          },
        ],
      },
    ],
    text: {
      format: zodTextFormat(importPreviewSchema, "schedule_import_preview"),
    },
  });

  return response.output_parsed;
};

export const extractScheduleFromImage = async (input: {
  mimeType: string;
  base64Data: string;
  filename?: string;
}) => {
  const client = getOpenAIClient();

  const response = await client.responses.parse({
    model: process.env.OPENAI_IMPORT_MODEL ?? process.env.OPENAI_MODEL ?? "gpt-5-nano",
    input: [
      {
        role: "system",
        content: [{ type: "input_text", text: promptBase }],
      },
      {
        role: "user",
        content: [
          {
            type: "input_text",
            text: `この画像${input.filename ? ` (${input.filename})` : ""}から勤務情報を抽出してください。`,
          },
          {
            type: "input_image",
            image_url: `data:${input.mimeType};base64,${input.base64Data}`,
            detail: "auto",
          },
        ],
      },
    ],
    text: {
      format: zodTextFormat(importPreviewSchema, "schedule_import_preview"),
    },
  });

  return response.output_parsed;
};
