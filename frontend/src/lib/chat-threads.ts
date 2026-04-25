// 役割: チャットスレッドの取得・作成・更新に関する処理をまとめる。

import type { UIMessage } from "ai";
import { createClient } from "@/lib/supabase/server";

const DEFAULT_THREAD_TITLE = "New chat";

const compactPartsForStorage = (parts: UIMessage["parts"]) => {
  return parts.map((part) => {
    if (part.type !== "file") {
      return part;
    }

    return {
      ...part,
      url: "",
    };
  });
};

const deriveThreadTitle = (messages: UIMessage[]) => {
  const firstUserMessage = messages.find((message) => message.role === "user");
  if (!firstUserMessage) return DEFAULT_THREAD_TITLE;

  const textPart = firstUserMessage.parts.find((part) => part.type === "text");
  if (textPart && textPart.text.trim()) {
    return textPart.text.trim().slice(0, 40);
  }

  const filePart = firstUserMessage.parts.find((part) => part.type === "file");
  if (filePart?.filename) {
    return filePart.filename.slice(0, 40);
  }

  return DEFAULT_THREAD_TITLE;
};

export const listChatThreads = async (userId: string) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("chat_threads")
    .select("id,title,created_at,updated_at")
    .eq("user_id", userId)
    .order("updated_at", { ascending: false });

  if (error) {
    throw new Error(error.message);
  }

  return data ?? [];
};

export const createChatThread = async (userId: string, title = DEFAULT_THREAD_TITLE) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("chat_threads")
    .insert({
      user_id: userId,
      title,
    })
    .select("id,title,created_at,updated_at")
    .single();

  if (error) {
    throw new Error(error.message);
  }

  return data;
};

export const getChatThread = async (userId: string, threadId: string) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("chat_threads")
    .select("id,title,created_at,updated_at")
    .eq("user_id", userId)
    .eq("id", threadId)
    .maybeSingle();

  if (error) {
    throw new Error(error.message);
  }

  return data;
};

export const renameChatThread = async (userId: string, threadId: string, title: string) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("chat_threads")
    .update({ title })
    .eq("user_id", userId)
    .eq("id", threadId);

  if (error) {
    throw new Error(error.message);
  }
};

export const deleteChatThread = async (userId: string, threadId: string) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("chat_threads")
    .delete()
    .eq("user_id", userId)
    .eq("id", threadId);

  if (error) {
    throw new Error(error.message);
  }
};

export const listChatMessages = async (userId: string, threadId: string): Promise<UIMessage[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("chat_messages")
    .select("id,role,parts,metadata")
    .eq("user_id", userId)
    .eq("thread_id", threadId)
    .order("message_order", { ascending: true });

  if (error) {
    throw new Error(error.message);
  }

  return (data ?? []).map((message) => ({
    id: message.id,
    role: message.role,
    parts: (message.parts ?? []) as UIMessage["parts"],
    metadata: (message.metadata ?? {}) as UIMessage["metadata"],
  }));
};

export const replaceChatMessages = async (userId: string, threadId: string, messages: UIMessage[]) => {
  const supabase = await createClient();

  const { error: deleteError } = await supabase
    .from("chat_messages")
    .delete()
    .eq("user_id", userId)
    .eq("thread_id", threadId);

  if (deleteError) {
    throw new Error(deleteError.message);
  }

  if (!messages.length) {
    return;
  }

  const payload = messages.map((message, index) => ({
    thread_id: threadId,
    user_id: userId,
    message_order: index,
    role: message.role,
    parts: compactPartsForStorage(message.parts),
    metadata: message.metadata ?? {},
  }));

  const { error: insertError } = await supabase.from("chat_messages").insert(payload);
  if (insertError) {
    throw new Error(insertError.message);
  }

  const currentThread = await getChatThread(userId, threadId);
  if (!currentThread) return;

  const nextTitle =
    currentThread.title === DEFAULT_THREAD_TITLE ? deriveThreadTitle(messages) : currentThread.title;

  const { error: updateError } = await supabase
    .from("chat_threads")
    .update({
      title: nextTitle,
      updated_at: new Date().toISOString(),
    })
    .eq("user_id", userId)
    .eq("id", threadId);

  if (updateError) {
    throw new Error(updateError.message);
  }
};

export { DEFAULT_THREAD_TITLE };
