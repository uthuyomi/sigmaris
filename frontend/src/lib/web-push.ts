import webpush from "web-push";

export const hasWebPushConfig = () =>
  Boolean(
    process.env.NEXT_PUBLIC_WEB_PUSH_PUBLIC_KEY &&
      process.env.WEB_PUSH_PRIVATE_KEY &&
      process.env.WEB_PUSH_SUBJECT,
  );

export const configureWebPush = () => {
  if (!hasWebPushConfig()) {
    throw new Error("Web Push environment variables are not configured.");
  }

  webpush.setVapidDetails(
    process.env.WEB_PUSH_SUBJECT!,
    process.env.NEXT_PUBLIC_WEB_PUSH_PUBLIC_KEY!,
    process.env.WEB_PUSH_PRIVATE_KEY!,
  );

  return webpush;
};
