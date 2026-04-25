// 役割: バックエンドAPIのチャット機能を呼び出すフロントエンド用ヘルパーをまとめる。

import { fetchBackendJson } from "@/lib/backend/client";

export type BackendChatCapabilities = {
  ok: boolean;
  backendTools: string[];
  notes: string[];
};

export async function readBackendChatCapabilities() {
  try {
    const data = await fetchBackendJson<BackendChatCapabilities>("/api/chat/capabilities");
    return {
      ready: true,
      data,
    };
  } catch (error) {
    return {
      ready: false,
      error: error instanceof Error ? error.message : "Backend chat capabilities unavailable",
    };
  }
}
