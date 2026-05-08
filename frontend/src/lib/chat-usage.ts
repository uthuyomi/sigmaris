import { createClient } from "@/lib/supabase/server";

export const FREE_CHAT_MESSAGE_LIMIT = 20;

export type ChatUsageStatus = {
  used: number;
  limit: number;
  remaining: number;
  limited: boolean;
};

export const readChatUsageStatus = async (userId: string): Promise<ChatUsageStatus> => {
  const supabase = await createClient();
  const { count, error } = await supabase
    .from("chat_messages")
    .select("id", { count: "exact", head: true })
    .eq("user_id", userId)
    .eq("role", "user");

  if (error) {
    if (error.code === "42P01" || error.message.includes("chat_messages")) {
      return {
        used: 0,
        limit: FREE_CHAT_MESSAGE_LIMIT,
        remaining: FREE_CHAT_MESSAGE_LIMIT,
        limited: false,
      };
    }
    throw new Error(error.message);
  }

  const used = count ?? 0;
  return {
    used,
    limit: FREE_CHAT_MESSAGE_LIMIT,
    remaining: Math.max(0, FREE_CHAT_MESSAGE_LIMIT - used),
    limited: used >= FREE_CHAT_MESSAGE_LIMIT,
  };
};
