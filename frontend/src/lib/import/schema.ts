// 役割: 予定取り込み機能で使う抽出結果と候補データのスキーマを定義する。
// IMPORT_EXTRACTION_REDESIGN: backend の ImportCandidate(pydantic)をミラー。
// 終日(allDay)・終了時刻任意・場所・読み取り根拠(evidence)に対応する。

import { z } from "zod";

export const importCandidateSchema = z
  .object({
    title: z.string().trim().min(1).max(120),
    date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe("YYYY-MM-DD"),
    startTime: z.string().regex(/^\d{2}:\d{2}$/).nullable().default(null).describe("HH:mm"),
    endTime: z.string().regex(/^\d{2}:\d{2}$/).nullable().default(null).describe("HH:mm"),
    allDay: z.boolean().default(false),
    location: z.string().max(500).nullable().default(null),
    description: z.string().max(2000).nullable().default(null),
    evidence: z.string().max(500).nullable().default(null).describe("読み取り根拠の引用"),
    confidence: z.number().min(0).max(1).nullable().default(null),
  })
  .refine(
    (c) => (c.allDay ? c.startTime === null && c.endTime === null : c.startTime !== null),
    {
      message:
        "all-day candidate must not carry times; timed candidate requires startTime",
    },
  );

export const importPreviewSchema = z.object({
  summary: z.string().max(2000),
  candidates: z.array(importCandidateSchema).max(100),
});

export type ImportCandidate = z.infer<typeof importCandidateSchema>;
export type ImportPreview = z.infer<typeof importPreviewSchema>;
