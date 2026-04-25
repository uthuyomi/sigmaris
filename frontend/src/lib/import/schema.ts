// 役割: 予定取り込み機能で使う抽出結果と候補データのスキーマを定義する。

import { z } from "zod";

export const importCandidateSchema = z.object({
  title: z.string().trim().min(1).max(120),
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe("YYYY-MM-DD"),
  startTime: z.string().regex(/^\d{2}:\d{2}$/).describe("HH:mm"),
  endTime: z.string().regex(/^\d{2}:\d{2}$/).describe("HH:mm"),
  description: z.string().max(2000).nullable(),
  confidence: z.number().min(0).max(1).nullable(),
});

export const importPreviewSchema = z.object({
  summary: z.string().max(2000),
  candidates: z.array(importCandidateSchema).max(100),
});

export type ImportCandidate = z.infer<typeof importCandidateSchema>;
export type ImportPreview = z.infer<typeof importPreviewSchema>;
