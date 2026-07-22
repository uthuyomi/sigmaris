// 役割: プレビュー済み予定候補をアプリDBと外部カレンダーへ保存するNext.js API Route。
import { NextResponse } from "next/server";
import { z } from "zod";
import { createEventsForUser } from "@/lib/event-data/writes";
import { createGoogleCalendarEvents } from "@/lib/google/calendar";
import { importCandidateSchema } from "@/lib/import/schema";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  target: z.enum(["google-calendar", "app-calendar"]),
  candidates: z.array(importCandidateSchema).max(100),
  sourceType: z.enum(["sheet", "image"]).optional(),
});

const toIsoDateTime = (date: string, time: string) => `${date}T${time}:00+09:00`;

// 候補 → Google 書き込みイベント。終日(allDay)は date を、時刻ありは
// start/end(ISO)を出し分ける。終了時刻なしは開始と同じにフォールバック。
const toCalendarWriteEvent = (candidate: z.infer<typeof importCandidateSchema>) => {
  if (candidate.allDay) {
    return {
      title: candidate.title,
      allDay: true as const,
      date: candidate.date,
      description: candidate.description ?? undefined,
      location: candidate.location ?? undefined,
    };
  }
  const start = toIsoDateTime(candidate.date, candidate.startTime as string);
  const end = candidate.endTime
    ? toIsoDateTime(candidate.date, candidate.endTime)
    : start;
  return {
    title: candidate.title,
    start,
    end,
    description: candidate.description ?? undefined,
    location: candidate.location ?? undefined,
  };
};

type ImportedSourceType = "sheet" | "image";

// app-calendar ターゲット(明示指定時のみ)用。Google 一本化により既定の
// 取り込み経路(google-calendar)からは呼ばれないが、可逆性のため残置。
const saveCandidatesToAppCalendar = async (
  userId: string,
  candidates: z.infer<typeof importCandidateSchema>[],
  options?: {
    sourceType?: ImportedSourceType;
  },
) => {
  const sourceType = options?.sourceType ?? "sheet";
  return createEventsForUser(
    userId,
    candidates.map((candidate) => {
      // 終日/終了時刻なしに対応: 終日や時刻なしは日付の 00:00 を、終了時刻
      // なしは開始と同じ時刻を既定にする(app-calendar ターゲット用の保険)。
      const startsAt = candidate.allDay
        ? toIsoDateTime(candidate.date, "00:00")
        : toIsoDateTime(candidate.date, candidate.startTime as string);
      const endsAt = candidate.allDay
        ? startsAt
        : toIsoDateTime(candidate.date, candidate.endTime ?? (candidate.startTime as string));
      return {
        title: candidate.title,
        description: candidate.description,
        startsAt,
        endsAt,
        sourceType,
        externalEventId: null,
        calendarConnectionId: null,
        metadata: {
          importedFrom: sourceType,
        },
      };
    }),
  );
};

export async function POST(req: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const parsed = requestSchema.parse(await req.json());

  if (parsed.target === "app-calendar") {
    const createdAppEvents = await saveCandidatesToAppCalendar(user.id, parsed.candidates, {
      sourceType: parsed.sourceType,
    });

    return NextResponse.json({
      ok: true,
      target: parsed.target,
      createdCount: createdAppEvents.length,
      createdAppEvents,
    });
  }

  try {
    // Google 一本化(IMPORT_EXTRACTION_REDESIGN の整合メモで選択): 取り込みの
    // 既定登録先は Google カレンダーのみ。以前は saveCandidatesToAppCalendar
    // で app(events テーブル)にも二重書きしていたが、AI チャット側の Google
    // 一本化と揃えて外した。可逆性のため saveCandidatesToAppCalendar 関数と
    // app-calendar ターゲット分岐は残置しており、ここで再度呼べば復帰できる。
    const created = await createGoogleCalendarEvents(
      parsed.candidates.map((candidate) => toCalendarWriteEvent(candidate)),
    );

    return NextResponse.json({
      ok: true,
      target: parsed.target,
      createdCount: created.length,
      created,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Google Calendar sync failed." },
      { status: 400 },
    );
  }
}
