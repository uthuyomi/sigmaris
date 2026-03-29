import { NextRequest, NextResponse } from "next/server";
import { persistGoogleProviderCookies } from "@/lib/google/provider-tokens";
import { createClient } from "@/lib/supabase/server";

const normalizeNextPath = (candidate: string | null) => {
  if (!candidate || !candidate.startsWith("/")) {
    return "/";
  }

  return candidate;
};

export async function GET(request: NextRequest) {
  const requestUrl = new URL(request.url);
  const code = requestUrl.searchParams.get("code");
  const next = normalizeNextPath(requestUrl.searchParams.get("next"));

  if (code) {
    const supabase = await createClient();
    const { data, error } = await supabase.auth.exchangeCodeForSession(code);

    if (error) {
      const errorUrl = new URL(
        `/settings?authError=${encodeURIComponent(error.message)}`,
        request.url,
      );
      return NextResponse.redirect(errorUrl);
    }

    await persistGoogleProviderCookies(data.session);
  }

  return NextResponse.redirect(new URL(next, request.url));
}
