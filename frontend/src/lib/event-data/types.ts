// 役割: 予定データ保存層で使う型定義をまとめる。

import type { EventItem } from "@/lib/mock-schedule";

export type EventRow = {
  id: string;
  user_id?: string;
  title: string;
  description: string | null;
  location_text: string | null;
  starts_at: string;
  ends_at: string;
  source_type: "manual" | "chat" | "sheet" | "image" | "calendar_sync";
  external_event_id: string | null;
  metadata?: Record<string, unknown> | null;
};

export type EventTone = EventItem["tone"];
