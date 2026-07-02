// 役割: チャットスレッドの取得・作成・更新に関する処理をまとめる。
// バックエンド(FastAPI)のREST APIを呼ぶ薄いプロキシとして実装する。
// 会話履歴の正はバックエンド側(app/services/app_chat_data.py)に一本化されている。

import type { UIMessage } from "ai";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { BackendApiError, fetchBackendJson } from "@/lib/backend/client";

const DEFAULT_THREAD_TITLE = "新しいチャット";

type ChatThreadRecord = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  version?: number;
};

type ChatMessageRecord = {
  id: string;
  role: UIMessage["role"];
  parts: UIMessage["parts"];
  metadata?: UIMessage["metadata"];
};

export const listChatThreads = async (userId: string) => {
  void userId; // ユーザーはバックエンドがJWTから解決する。シグネチャ互換のため残す。
  const headers = await readBackendAuthHeaders();
  const data = await fetchBackendJson<{ threads: ChatThreadRecord[] }>(
    "/api/app/chat/threads",
    { method: "GET", headers },
  );
  return data.threads;
};

export const createChatThread = async (
  userId: string,
  options: { id?: string; title?: string } = {},
) => {
  void userId;
  const headers = await readBackendAuthHeaders();
  const data = await fetchBackendJson<{ thread: ChatThreadRecord }>(
    "/api/app/chat/threads",
    {
      method: "POST",
      headers,
      body: JSON.stringify({ threadId: options.id, title: options.title }),
    },
  );
  return data.thread;
};

export const getChatThread = async (userId: string, threadId: string) => {
  void userId;
  const headers = await readBackendAuthHeaders();
  const data = await fetchBackendJson<{ thread: ChatThreadRecord | null }>(
    `/api/app/chat/threads/${threadId}`,
    { method: "GET", headers },
  );
  return data.thread;
};

export const renameChatThread = async (userId: string, threadId: string, title: string) => {
  void userId;
  const headers = await readBackendAuthHeaders();
  await fetchBackendJson(`/api/app/chat/threads/${threadId}`, {
    method: "PATCH",
    headers,
    body: JSON.stringify({ title }),
  });
};

export const deleteChatThread = async (userId: string, threadId: string) => {
  void userId;
  const headers = await readBackendAuthHeaders();
  await fetchBackendJson(`/api/app/chat/threads/${threadId}`, {
    method: "DELETE",
    headers,
  });
};

export const listChatMessages = async (userId: string, threadId: string): Promise<UIMessage[]> => {
  void userId;
  const headers = await readBackendAuthHeaders();
  const data = await fetchBackendJson<{ messages: ChatMessageRecord[] }>(
    `/api/app/chat/threads/${threadId}/messages`,
    { method: "GET", headers },
  );
  return data.messages.map((message) => ({
    id: message.id,
    role: message.role,
    parts: message.parts,
    metadata: message.metadata ?? {},
  })) as UIMessage[];
};

// Phase A4: this path currently has no live caller (Phase A0 confirmed
// zero callers), so this is unexercised by production traffic. Implemented
// anyway for correctness if something starts using it: reads the thread's
// current `version`, sends it as expectedVersion, and — on a 409 conflict
// (another writer replaced this thread's messages first) — refetches the
// now-current version and retries once. A conflict on the retry propagates
// to the caller rather than looping indefinitely or attempting to merge
// content (per Phase A4's "keep conflict resolution simple" direction).
export const replaceChatMessages = async (userId: string, threadId: string, messages: UIMessage[]) => {
  void userId;
  const headers = await readBackendAuthHeaders();

  const attempt = async (): Promise<void> => {
    const thread = await getChatThread(userId, threadId);
    await fetchBackendJson("/api/app/chat/messages/replace", {
      method: "POST",
      headers,
      body: JSON.stringify({ threadId, messages, expectedVersion: thread?.version }),
    });
  };

  try {
    await attempt();
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 409) {
      await attempt(); // one retry against the now-current version
      return;
    }
    throw error;
  }
};

export { DEFAULT_THREAD_TITLE };
