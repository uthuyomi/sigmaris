"use client";
// 役割: ログイン・ログアウトなど認証操作を表示するReactクライアントコンポーネント。


import { createClient, hasSupabaseConfig } from "@/lib/supabase/client";
import { getDictionary, type AppLocale } from "@/lib/i18n";
import type { User } from "@supabase/supabase-js";
import { LogInIcon, LogOutIcon } from "lucide-react";
import { useEffect, useState } from "react";

const googleScopes = [
  "openid",
  "email",
  "profile",
  "https://www.googleapis.com/auth/calendar",
  "https://www.googleapis.com/auth/spreadsheets.readonly",
].join(" ");

type AuthControlsProps = {
  redirectPath?: string;
  locale: AppLocale;
  mode?: "compact" | "hero";
};

export function AuthControls({
  redirectPath,
  locale,
  mode = "compact",
}: AuthControlsProps) {
  const dict = getDictionary(locale);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(false);
  const [available, setAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!hasSupabaseConfig()) {
      return;
    }

    const supabase = createClient();
    setAvailable(true);

    supabase.auth.getUser().then(({ data }) => {
      setUser(data.user ?? null);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  const nextPath =
    redirectPath ??
    (typeof window !== "undefined" ? window.location.pathname : "/app");

  const signInWithGoogle = async () => {
    if (!hasSupabaseConfig()) return;

    try {
      setLoading(true);
      setError(null);

      const supabase = createClient();
      const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(
        nextPath,
      )}`;

      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo,
          scopes: googleScopes,
          queryParams: {
            access_type: "offline",
            prompt: "consent",
            include_granted_scopes: "true",
          },
        },
      });

      if (error) throw error;
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : dict.auth.signInError);
      setLoading(false);
    }
  };

  const signOut = async () => {
    if (!hasSupabaseConfig()) return;

    try {
      setLoading(true);
      setError(null);

      const supabase = createClient();
      await supabase.auth.signOut();
      await fetch("/auth/signout", { method: "POST" });
      window.location.assign("/");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : dict.auth.signOutError);
      setLoading(false);
    }
  };

  if (!available) {
    return (
      <div className="rounded-full border border-stone-900/10 bg-white px-4 py-2 text-sm text-stone-500">
        {dict.auth.unavailable}
      </div>
    );
  }

  if (user) {
    return (
      <div className="flex flex-col items-start gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="rounded-full border border-stone-900/10 bg-white px-4 py-2 text-sm text-stone-700">
            {user.email ?? dict.auth.signedInAs}
          </div>
          <button
            type="button"
            onClick={signOut}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50 disabled:opacity-50"
          >
            <LogOutIcon className="size-4" />
            {dict.auth.signOut}
          </button>
        </div>
        {error ? <p className="text-xs text-red-600">{error}</p> : null}
      </div>
    );
  }

  const buttonClass =
    mode === "hero"
      ? "inline-flex items-center gap-2 rounded-full bg-stone-900 px-6 py-3 text-base font-semibold text-stone-50 disabled:opacity-50"
      : "inline-flex items-center gap-2 rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50 disabled:opacity-50";

  return (
    <div className="flex flex-col items-start gap-2">
      <button type="button" onClick={signInWithGoogle} disabled={loading} className={buttonClass}>
        <LogInIcon className="size-4" />
        {loading ? dict.auth.signingIn : dict.auth.signIn}
      </button>
      {error ? <p className="text-xs text-red-600">{error}</p> : null}
    </div>
  );
}
