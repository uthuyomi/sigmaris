import { google } from "googleapis";

const requiredEnv = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"] as const;

export const hasGoogleOAuthConfig = () =>
  requiredEnv.every((key) => Boolean(process.env[key]));

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

  const refreshToken = tokens?.refreshToken ?? process.env.GOOGLE_REFRESH_TOKEN;
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
