import { zodTextFormat } from "openai/helpers/zod";
import { getOpenAIClient } from "@/lib/openai/client";
import { importPreviewSchema, type ImportPreview } from "@/lib/import/schema";

const promptBase = [
  "あなたは勤務表や予定表の画像・表データを、予定候補へ構造化する抽出エンジンです。",
  "読み取れた内容だけを使い、推測しすぎないでください。",
  "出力は schedule_import_preview スキーマに厳密に従ってください。",
  "summary には抽出できた件数や注意点を短く書いてください。",
  "candidates には date を YYYY-MM-DD、startTime と endTime を HH:mm で入れてください。",
  "日付や時間が曖昧な項目は candidates に含めず、summary で不足情報を説明してください。",
  "タイトルが明確でなければ title は 勤務 を使ってください。",
].join("\n");

const ensureParsedOutput = (
  parsed: ImportPreview | null | undefined,
  fallbackMessage: string,
): ImportPreview => {
  if (!parsed) {
    throw new Error(fallbackMessage);
  }

  return parsed;
};

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
              "以下の表データから勤務や予定の候補を抽出してください。",
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

  return ensureParsedOutput(
    response.output_parsed,
    "シートの解析結果を構造化できませんでした。",
  );
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
            text: `この画像${input.filename ? ` (${input.filename})` : ""}から勤務や予定の候補を抽出してください。`,
          },
          {
            type: "input_image",
            image_url: `data:${input.mimeType};base64,${input.base64Data}`,
            detail: "high",
          },
        ],
      },
    ],
    text: {
      format: zodTextFormat(importPreviewSchema, "schedule_import_preview"),
    },
  });

  return ensureParsedOutput(
    response.output_parsed,
    "画像の解析結果を構造化できませんでした。",
  );
};
