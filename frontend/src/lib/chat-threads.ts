// 役割: チャットスレッドの取得・作成・更新に関する処理をまとめる。
// バックエンド(FastAPI)のREST APIを呼ぶ薄いプロキシとして実装する。
// 会話履歴の正はバックエンド側(app/services/app_chat_data.py)に一本化されている。

import type { UIMessage } from "ai";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { fetchBackendJson } from "@/lib/backend/client";

const DEFAULT_THREAD_TITLE = "新しいチャット";

type ChatThreadRecord = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
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

export const replaceChatMessages = async (userId: string, threadId: string, messages: UIMessage[]) => {
  void userId;
  const headers = await readBackendAuthHeaders();
  await fetchBackendJson("/api/app/chat/messages/replace", {
    method: "POST",
    headers,
    body: JSON.stringify({ threadId, messages }),
  });
};

export { DEFAULT_THREAD_TITLE };
