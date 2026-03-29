import { openai } from "@ai-sdk/openai";
import { frontendTools } from "@assistant-ui/react-ai-sdk";
import {
  convertToModelMessages,
  JSONSchema7,
  stepCountIs,
  streamText,
  tool,
  type UIMessage,
} from "ai";
import { z } from "zod";
import { createGoogleCalendarEvents } from "@/lib/google/calendar";
import { readGoogleSheetPreview } from "@/lib/google/sheets";

const createCalendarEventsTool = tool({
  description:
    "Google Calendar に予定を登録する。内容を確認したあとでだけ実行する。",
  inputSchema: z.object({
    calendarId: z.string().optional(),
    events: z.array(
      z.object({
        title: z.string(),
        start: z.string().describe("ISO 8601 datetime"),
        end: z.string().describe("ISO 8601 datetime"),
        description: z.string().optional(),
        location: z.string().optional(),
      }),
    ),
  }),
  execute: async ({ calendarId, events }) => {
    try {
      const created = await createGoogleCalendarEvents(events, calendarId);

      return {
        ok: true,
        createdCount: created.length,
        created,
      };
    } catch (error) {
      return {
        ok: false,
        reason:
          error instanceof Error
            ? error.message
            : "Google Calendar 連携を実行できませんでした。",
      };
    }
  },
});

const readGoogleSheetTool = tool({
  description:
    "Google Sheets の URL から先頭シートの表データを読み取る。",
  inputSchema: z.object({
    url: z.string().url(),
  }),
  execute: async ({ url }) => {
    try {
      const preview = await readGoogleSheetPreview(url);

      return {
        ok: true,
        spreadsheetId: preview.spreadsheetId,
        sheetTitle: preview.sheetTitle,
        rows: preview.rows.slice(0, 20),
        rowCount: preview.rows.length,
      };
    } catch (error) {
      return {
        ok: false,
        reason:
          error instanceof Error
            ? error.message
            : "Google Sheets を読み取れませんでした。",
      };
    }
  },
});

export async function POST(req: Request) {
  if (!process.env.OPENAI_API_KEY) {
    return new Response(
      JSON.stringify({
        error:
          "OPENAI_API_KEY is not set. Copy .env.example to .env.local and set your API key.",
      }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      },
    );
  }

  const {
    messages,
    system,
    tools,
  }: {
    messages: UIMessage[];
    system?: string;
    tools?: Record<string, { description?: string; parameters: JSONSchema7 }>;
  } = await req.json();

  const result = streamText({
    model: openai(process.env.OPENAI_MODEL ?? "gpt-5-nano"),
    messages: await convertToModelMessages(messages),
    tools: {
      ...frontendTools(tools ?? {}),
      read_google_sheet: readGoogleSheetTool,
      create_google_calendar_events: createCalendarEventsTool,
    },
    stopWhen: stepCountIs(5),
    system:
      system ??
      [
        "あなたは ShiftPilotAI の予定調整アシスタントです。",
        "日本語で簡潔に話してください。",
        "開始時刻と終了時刻を明示して提案してください。",
        "時間調整は 24 時間タイムラインで扱う前提で考えてください。",
        "画像や Google Sheets URL から勤務情報を読み取る導線があります。",
        "Google Sheets の URL が来たら、必要に応じて read_google_sheet を使って内容を確認してください。",
        "Google Calendar へ登録するときは、必ずユーザーの確認を取ってから create_google_calendar_events を使ってください。",
      ].join("\n"),
  });

  return result.toUIMessageStreamResponse();
}
