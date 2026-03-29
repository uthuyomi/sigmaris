import { NextResponse } from "next/server";
import { z } from "zod";
import { createGoogleCalendarEvents } from "@/lib/google/calendar";
import { importCandidateSchema } from "@/lib/import/schema";

const requestSchema = z.object({
  target: z.enum(["google-calendar", "app-calendar"]),
  candidates: z.array(importCandidateSchema),
});

const toIsoDateTime = (date: string, time: string) => `${date}T${time}:00+09:00`;

export async function POST(req: Request) {
  const parsed = requestSchema.parse(await req.json());

  if (parsed.target === "app-calendar") {
    return NextResponse.json({
      ok: true,
      target: parsed.target,
      createdCount: parsed.candidates.length,
      note: "自前カレンダー保存は次段階。今は Google Calendar を優先している。",
    });
  }

  try {
    const created = await createGoogleCalendarEvents(
      parsed.candidates.map((candidate) => ({
        title: candidate.title,
        start: toIsoDateTime(candidate.date, candidate.startTime),
        end: toIsoDateTime(candidate.date, candidate.endTime),
        description: candidate.description,
      })),
    );

    return NextResponse.json({
      ok: true,
      target: parsed.target,
      createdCount: created.length,
      created,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Google Calendar 反映に失敗しました。" },
      { status: 400 },
    );
  }
}
