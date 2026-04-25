// 役割: Google連携で使うプロバイダートークンの取得処理をまとめる。

import type { Session } from "@supabase/supabase-js";
import { cookies } from "next/headers";

const accessTokenCookie = "sp_google_access_token";
const refreshTokenCookie = "sp_google_refresh_token";

const baseCookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
};

export const readGoogleProviderTokens = async () => {
  const cookieStore = await cookies();

  return {
    accessToken: cookieStore.get(accessTokenCookie)?.value,
    refreshToken: cookieStore.get(refreshTokenCookie)?.value,
  };
};

export const persistGoogleProviderCookies = async (session: Session | null) => {
  if (!session) return;

  const cookieStore = await cookies();

  if (session.provider_token) {
    cookieStore.set(accessTokenCookie, session.provider_token, {
      ...baseCookieOptions,
      maxAge: 60 * 60,
    });
  }

  if (session.provider_refresh_token) {
    cookieStore.set(refreshTokenCookie, session.provider_refresh_token, {
      ...baseCookieOptions,
      maxAge: 60 * 60 * 24 * 30,
    });
  }
};

export const clearGoogleProviderCookies = async () => {
  const cookieStore = await cookies();
  cookieStore.delete(accessTokenCookie);
  cookieStore.delete(refreshTokenCookie);
};
