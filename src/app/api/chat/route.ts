import { openai } from "@ai-sdk/openai";
import { frontendTools } from "@assistant-ui/react-ai-sdk";
import {
  convertToModelMessages,
  stepCountIs,
  streamText,
  tool,
  type FileUIPart,
  type JSONSchema7,
  type UIMessage,
} from "ai";
import { z } from "zod";
import {
  createGoogleCalendarEvents,
  listGoogleCalendarEvents,
} from "@/lib/google/calendar";
import { getSimpleRoutePlan, getTransitRoutePlan } from "@/lib/google/maps";
import { readGoogleSheetPreview } from "@/lib/google/sheets";
import { extractScheduleFromImage } from "@/lib/import/extract";

const listCalendarEventsTool = tool({
  description:
    "Google Calendar から予定を読み取る。指定時間帯や検索語で予定確認するときに使う。",
  inputSchema: z.object({
    calendarId: z.string().optional(),
    timeMin: z.string().optional().describe("ISO 8601 datetime"),
    timeMax: z.string().optional().describe("ISO 8601 datetime"),
    maxResults: z.number().int().min(1).max(50).optional(),
    query: z.string().optional(),
  }),
  execute: async (input) => {
    try {
      const events = await listGoogleCalendarEvents(input);
      return {
        ok: true,
        events,
        count: events.length,
      };
    } catch (error) {
      return {
        ok: false,
        reason:
          error instanceof Error
            ? error.message
            : "Google Calendar の予定取得に失敗しました。",
      };
    }
  },
});

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
            : "Google Calendar への登録に失敗しました。",
      };
    }
  },
});

const readGoogleSheetTool = tool({
  description:
    "Google Sheets の URL から表データを読み取る。勤務表や一覧表の確認に使う。",
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

const planRouteTool = tool({
  description:
    "Google Maps を使って移動時間と推奨出発時刻を調べる。到着時刻や出発時刻の確認に使う。",
  inputSchema: z.object({
    origin: z.string(),
    destination: z.string(),
    travelMode: z.enum(["transit", "driving", "walking"]),
    arrivalTimeIso: z.string().optional().describe("公共交通では到着希望時刻"),
    departureTimeIso: z.string().optional().describe("車や徒歩では出発時刻"),
  }),
  execute: async ({ origin, destination, travelMode, arrivalTimeIso, departureTimeIso }) => {
    try {
      const plan =
        travelMode === "transit"
          ? await getTransitRoutePlan({
              origin,
              destination,
              arrivalTimeIso: arrivalTimeIso ?? new Date().toISOString(),
            })
          : await getSimpleRoutePlan({
              origin,
              destination,
              departureTimeIso: departureTimeIso ?? new Date().toISOString(),
              mode: travelMode,
            });

      return {
        ok: true,
        plan,
      };
    } catch (error) {
      return {
        ok: false,
        reason:
          error instanceof Error
            ? error.message
            : "Google Maps の経路計算に失敗しました。",
      };
    }
  },
});

type ExtractedImageContext =
  | {
      filename: string;
      extracted: Awaited<ReturnType<typeof extractScheduleFromImage>>;
    }
  | {
      filename: string;
      error: string;
    };

const extractLatestImageContexts = async (messages: UIMessage[]) => {
  const latestUserMessage = [...messages].reverse().find((message) => message.role === "user");
  if (!latestUserMessage) return [] satisfies ExtractedImageContext[];

  const fileParts = latestUserMessage.parts.filter(
    (part): part is FileUIPart => part.type === "file" && part.mediaType.startsWith("image/"),
  );

  const contexts: ExtractedImageContext[] = [];

  for (const file of fileParts) {
    try {
      const base64Data = file.url.includes(",") ? file.url.split(",")[1] ?? "" : "";
      if (!base64Data) {
        contexts.push({
          filename: file.filename ?? "image",
          error: "画像データを取得できませんでした。",
        });
        continue;
      }

      const extracted = await extractScheduleFromImage({
        mimeType: file.mediaType,
        base64Data,
        filename: file.filename,
      });

      contexts.push({
        filename: file.filename ?? "image",
        extracted,
      });
    } catch (error) {
      contexts.push({
        filename: file.filename ?? "image",
        error: error instanceof Error ? error.message : "画像解析に失敗しました。",
      });
    }
  }

  return contexts;
};

const buildAttachmentContext = async (messages: UIMessage[]) => {
  const imageContexts = await extractLatestImageContexts(messages);
  if (!imageContexts.length) return "";

  return [
    "最新のユーザーメッセージには画像添付が含まれている。",
    "以下は画像から抽出した予定候補の要約。これを前提に会話し、画像が未着とは言わないこと。",
    ...imageContexts.map((context, index) => {
      if ("error" in context) {
        return `画像${index + 1} (${context.filename}): 解析失敗 - ${context.error}`;
      }

      return [
        `画像${index + 1} (${context.filename})`,
        `summary: ${context.extracted.summary}`,
        `candidates: ${JSON.stringify(context.extracted.candidates)}`,
      ].join("\n");
    }),
  ].join("\n\n");
};

const sanitizeMessagesForModel = (
  messages: UIMessage[],
  attachmentContext: string,
): UIMessage[] => {
  let injected = false;

  return messages.map((message) => {
    if (message.role !== "user") {
      return {
        ...message,
        parts: message.parts.filter((part) => part.type !== "file"),
      };
    }

    const hasFile = message.parts.some((part) => part.type === "file");
    const filteredParts = message.parts.filter((part) => part.type !== "file");

    if (!hasFile || !attachmentContext || injected) {
      return {
        ...message,
        parts: filteredParts,
      };
    }

    injected = true;

    return {
      ...message,
      parts: [
        {
          type: "text",
          text: [
            "添付画像の解析結果を受け取りました。以下を前提に回答してください。",
            attachmentContext,
          ].join("\n\n"),
        },
        ...filteredParts,
      ],
    };
  });
};

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

  const latestUserMessage = [...messages].reverse().find((message) => message.role === "user");
  const latestFileCount =
    latestUserMessage?.parts.filter((part) => part.type === "file").length ?? 0;
  console.log("[chat] incoming", {
    messageCount: messages.length,
    latestFileCount,
    latestParts: latestUserMessage?.parts.map((part) => part.type) ?? [],
  });

  const attachmentContext = await buildAttachmentContext(messages);
  console.log("[chat] attachmentContext", {
    hasAttachmentContext: attachmentContext.length > 0,
    preview: attachmentContext.slice(0, 300),
  });

  const messagesForModel = sanitizeMessagesForModel(messages, attachmentContext);

  const result = streamText({
    model: openai(process.env.OPENAI_MODEL ?? "gpt-5-nano"),
    messages: await convertToModelMessages(messagesForModel),
    tools: {
      ...frontendTools(tools ?? {}),
      list_google_calendar_events: listCalendarEventsTool,
      create_google_calendar_events: createCalendarEventsTool,
      read_google_sheet: readGoogleSheetTool,
      plan_google_route: planRouteTool,
    },
    stopWhen: stepCountIs(6),
    system: [
      system,
      [
        "あなたは ShiftPilotAI の予定調整アシスタントです。",
        "日本語で簡潔に話してください。",
        "時刻の相談では開始時刻と終了時刻を明示してください。",
        "予定は 24 時間のタイムライン前提で扱ってください。",
        "Google Calendar へ登録する前に、登録対象の内容を要約して確認してください。",
        "Google Sheets の URL が渡されたら、必要に応じて read_google_sheet を使って表を確認してください。",
        "移動時間や到着可否が話題になったら、必要に応じて plan_google_route を使って出発時刻と所要時間を確認してください。",
        "画像解析結果が渡されているときは、それを前提に回答し、画像が見えていないとは言わないでください。",
        "画像から抽出した候補があるときは、その候補を整理して確認し、ユーザーが明示的に指示したあとでだけ登録してください。",
      ].join("\n"),
    ]
      .filter(Boolean)
      .join("\n\n"),
  });

  return result.toUIMessageStreamResponse();
}
