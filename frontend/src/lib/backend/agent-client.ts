// 役割: `/api/agent/*`(エージェント間インターフェース)への認証付きJSON取得をまとめる。
//
// `/memory`ページ用に個別実装されていたものを、`/timeline`ページでも同じ
// `/api/agent/*`呼び出しパターンが必要になったため、共有モジュールとして
// 切り出した(挙動は変更していない、純粋なリファクタリング)。

import { getBackendBaseUrl } from "@/lib/backend/client";

export type ApiResult<T> = {
  data: T | null;
  error: string | null;
};

type AgentHeaders = {
  "x-agent-id": string;
  "x-agent-secret": string;
};

export function readAgentHeaders(): AgentHeaders | null {
  const directId =
    process.env.AGENT_ID ??
    process.env.SIGMARIS_AGENT_ID ??
    process.env.SCHEDULE_AGENT_ID ??
    process.env.NEXT_PRIVATE_AGENT_ID;
  const directSecret =
    process.env.AGENT_SECRET ??
    process.env.SIGMARIS_AGENT_SECRET ??
    process.env.SCHEDULE_AGENT_SECRET ??
    process.env.NEXT_PRIVATE_AGENT_SECRET;

  if (directId && directSecret) {
    return {
      "x-agent-id": directId,
      "x-agent-secret": directSecret,
    };
  }

  const rawSecrets = process.env.AGENT_SECRETS;
  if (!rawSecrets) return null;

  try {
    const parsed = JSON.parse(rawSecrets) as Record<string, string>;
    const preferredId = directId ?? Object.keys(parsed)[0];
    const secret = preferredId ? parsed[preferredId] : undefined;
    if (!preferredId || !secret) return null;

    return {
      "x-agent-id": preferredId,
      "x-agent-secret": secret,
    };
  } catch {
    return null;
  }
}

export async function fetchAgentJson<T>(
  path: string,
  headers: Record<string, string>,
  init?: RequestInit,
): Promise<ApiResult<T>> {
  const agentHeaders = readAgentHeaders();
  if (!agentHeaders) {
    return {
      data: null,
      error: "AGENT_SECRETS またはエージェント認証用の環境変数が未設定です。",
    };
  }

  try {
    const response = await fetch(`${getBackendBaseUrl()}${path}`, {
      ...init,
      headers: {
        ...headers,
        ...agentHeaders,
        ...(init?.headers as Record<string, string> | undefined),
      },
      cache: "no-store",
    });

    if (!response.ok) {
      const detail = await response.text();
      return {
        data: null,
        error: `取得に失敗しました (${response.status})${detail ? `: ${detail.slice(0, 180)}` : ""}`,
      };
    }

    return {
      data: (await response.json()) as T,
      error: null,
    };
  } catch (error) {
    return {
      data: null,
      error: error instanceof Error ? error.message : "不明なエラーが発生しました。",
    };
  }
}
