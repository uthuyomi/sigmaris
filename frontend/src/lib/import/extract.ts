// 役割: シートや画像から予定候補を抽出するための共通処理をまとめる。

import { zodTextFormat } from "openai/helpers/zod";
import { getOpenAIClient } from "@/lib/openai/client";
import { importPreviewSchema, type ImportPreview } from "@/lib/import/schema";

// 注: このモジュールは現在どこからも呼ばれていない(実際の抽出はバックエンド
// import_extract.py が担当)。スキーマ整合のため zod スキーマ(終日/場所/
// evidence 対応済み)は共有しつつ、プロンプト文言も汎用化して drift を防ぐ。
const promptBase = [
  "あなたは画像・表データから予定(イベント)を構造化して抽出する抽出エンジンです。",
  "勤務表に限らず、チラシ・告知・スクショ・メモなど、日時を含むあらゆる予定を対象にします。",
  "読み取れた内容だけを使い、画像/表に無いものは作らないでください(根拠のない候補は出さない)。",
  "出力は schedule_import_preview スキーマに厳密に従ってください。",
  "summary には抽出できた件数や注意点を短く書いてください。予定が読み取れなければ candidates は空にします。",
  "candidates の date は YYYY-MM-DD。時刻ありは startTime(HH:mm)を、終日は allDay=true を設定し時刻は null にします。",
  "各候補には読み取り根拠(evidence)を元テキストの引用で付けてください。曖昧なら confidence を下げます。",
  "内容に応じたタイトルを付け、読み取れない場合のみ汎用名にしてください。",
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
