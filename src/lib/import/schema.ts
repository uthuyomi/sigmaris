import { z } from "zod";

export const importCandidateSchema = z.object({
  title: z.string(),
  date: z.string().describe("YYYY-MM-DD"),
  startTime: z.string().describe("HH:mm"),
  endTime: z.string().describe("HH:mm"),
  description: z.string().optional(),
  confidence: z.number().min(0).max(1).optional(),
});

export const importPreviewSchema = z.object({
  summary: z.string(),
  candidates: z.array(importCandidateSchema),
});

export type ImportCandidate = z.infer<typeof importCandidateSchema>;
export type ImportPreview = z.infer<typeof importPreviewSchema>;
