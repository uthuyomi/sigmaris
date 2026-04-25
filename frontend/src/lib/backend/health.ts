// 役割: バックエンドAPIのヘルスチェックをNext.js側から呼び出す処理をまとめる。

import { fetchBackendJson } from "@/lib/backend/client";

export type BackendHealth = {
  status: string;
  service: string;
  scope?: string;
};

export async function readBackendHealth() {
  try {
    const data = await fetchBackendJson<BackendHealth>("/api/health");
    return {
      ready: data.status === "ok",
      data,
    };
  } catch (error) {
    return {
      ready: false,
      error: error instanceof Error ? error.message : "Backend API unavailable",
    };
  }
}
