// 役割: Google OAuthの認可URL生成やトークン交換処理をまとめる。

import { google } from "googleapis";

const requiredEnv = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"] as const;
const invalidGrantPattern = /invalid_grant/i;

export const hasGoogleOAuthConfig = () =>
  requiredEnv.every((key) => Boolean(process.env[key]));

export const isGoogleInvalidGrantError = (error: unknown) => {
  if (!error) return false;
  if (error instanceof Error && invalidGrantPattern.test(error.message)) {
    return true;
  }

  if (typeof error === "object") {
    const candidate = error as {
      code?: unknown;
      response?: {
        data?: {
          error?: unknown;
          error_description?: unknown;
        };
      };
    };
    return (
      candidate.code === "invalid_grant" ||
      candidate.response?.data?.error === "invalid_grant" ||
      invalidGrantPattern.test(String(candidate.response?.data?.error_description ?? ""))
    );
  }

  return invalidGrantPattern.test(String(error));
};

export const createGoogleOAuthClient = (tokens?: {
  accessToken?: string;
  refreshToken?: string;
}) => {
  if (!hasGoogleOAuthConfig()) {
    throw new Error("Google OAuth environment variables are not fully configured.");
  }

  const client = new google.auth.OAuth2(
    process.env.GOOGLE_CLIENT_ID,
    process.env.GOOGLE_CLIENT_SECRET,
    process.env.GOOGLE_REDIRECT_URI,
  );

  const refreshToken = tokens?.refreshToken;
  const accessToken = tokens?.accessToken;

  if (!refreshToken && !accessToken) {
    throw new Error("Google OAuth token is not available.");
  }

  client.setCredentials({
    access_token: accessToken,
    refresh_token: refreshToken,
  });

  return client;
};
