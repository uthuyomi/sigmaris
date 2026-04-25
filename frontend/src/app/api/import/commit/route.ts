// 役割: プレビュー済み予定候補を外部カレンダーへ登録するNext.js API Route。

import { NextResponse } from "next/server";
import { z } from "zod";
import { createGoogleCalendarEvents } from "@/lib/google/calendar";
import { importCandidateSchema } from "@/lib/import/schema";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  target: z.enum(["google-calendar", "app-calendar"]),
  candidates: z.array(importCandidateSchema).max(100),
});

const toIsoDateTime = (date: string, time: string) => `${date}T${time}:00+09:00`;

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
    return NextResponse.json({
      ok: true,
      target: parsed.target,
      createdCount: parsed.candidates.length,
      note: "自前カレンダー保存は次段階。いまは Google Calendar 連携を優先している。",
    });
  }

  try {
    const created = await createGoogleCalendarEvents(
      parsed.candidates.map((candidate) => ({
        title: candidate.title,
        start: toIsoDateTime(candidate.date, candidate.startTime),
        end: toIsoDateTime(candidate.date, candidate.endTime),
        description: candidate.description ?? undefined,
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
