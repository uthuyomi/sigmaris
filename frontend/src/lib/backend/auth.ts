// 役割: バックエンドAPIへ渡す認証情報やセッション連携の処理をまとめる。

import { readGoogleProviderTokens } from "@/lib/google/provider-tokens";
import { createClient } from "@/lib/supabase/server";

export async function readBackendAuthHeaders() {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!session?.access_token || !user) {
    throw new Error("Supabase session is not available.");
  }

  const googleTokens = await readGoogleProviderTokens();

  return {
    Authorization: `Bearer ${session.access_token}`,
    "x-google-access-token": googleTokens.accessToken ?? "",
    "x-google-refresh-token": googleTokens.refreshToken ?? "",
  };
}
