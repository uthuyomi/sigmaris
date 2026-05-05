// 役割: アプリのトップページを表示するNext.jsページ。
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { LandingPageContent } from "@/components/landing";
import { landingCopies, resolveLandingLocale } from "@/i18n/landing";
import { getCurrentUser } from "@/lib/supabase/auth";

export default async function LandingPage() {
  const user = await getCurrentUser();

  if (user) {
    redirect("/app");
  }

  const requestHeaders = await headers();
  const locale = resolveLandingLocale(requestHeaders.get("accept-language"));
  const copy = landingCopies[locale];

  return <LandingPageContent copy={copy} />;
}
