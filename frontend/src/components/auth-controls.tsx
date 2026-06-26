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
  mode?: "compact" | "hero" | "icon" | "sigmaris";
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
    if (mode === "icon") {
      return null;
    }

    return (
      <div className="rounded-full border border-stone-900/10 bg-white px-4 py-2 text-sm text-stone-500">
        {dict.auth.unavailable}
      </div>
    );
  }

  if (user) {
    if (mode === "icon") {
      return (
        <div className="relative">
          <button
            type="button"
            onClick={signOut}
            disabled={loading}
            className="inline-flex size-10 items-center justify-center rounded-xl text-stone-500 transition hover:bg-stone-100 hover:text-stone-950 disabled:opacity-50 dark:text-stone-400 dark:hover:bg-white/10 dark:hover:text-white"
            aria-label={dict.auth.signOut}
            title={user.email ?? dict.auth.signOut}
          >
            <LogOutIcon className="size-[18px]" />
          </button>
          {error ? <p className="absolute right-0 top-11 w-48 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 shadow-sm">{error}</p> : null}
        </div>
      );
    }

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
    mode === "sigmaris"
      ? "inline-flex min-h-12 w-full items-center justify-center gap-3 rounded-full bg-white px-5 text-sm font-semibold text-[#212121] transition hover:bg-[#f2f2f2] disabled:opacity-50"
      : mode === "hero"
      ? "inline-flex items-center gap-2 rounded-full bg-stone-900 px-6 py-3 text-base font-semibold text-stone-50 disabled:opacity-50"
      : "inline-flex items-center gap-2 rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50 disabled:opacity-50";

  if (mode === "icon") {
    return (
      <div className="relative">
        <button
          type="button"
          onClick={signInWithGoogle}
          disabled={loading}
          className="inline-flex size-10 items-center justify-center rounded-xl text-stone-500 transition hover:bg-stone-100 hover:text-stone-950 disabled:opacity-50 dark:text-stone-400 dark:hover:bg-white/10 dark:hover:text-white"
          aria-label={loading ? dict.auth.signingIn : dict.auth.signIn}
          title={loading ? dict.auth.signingIn : dict.auth.signIn}
        >
          <LogInIcon className="size-[18px]" />
        </button>
        {error ? <p className="absolute right-0 top-11 w-48 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 shadow-sm">{error}</p> : null}
      </div>
    );
  }

  return (
    <div className={mode === "sigmaris" ? "flex w-full flex-col items-stretch gap-3" : "flex flex-col items-start gap-2"}>
      <button type="button" onClick={signInWithGoogle} disabled={loading} className={buttonClass}>
        {mode === "sigmaris" ? (
          <span className="flex size-5 items-center justify-center rounded-full bg-white font-sans text-base font-bold text-[#4285f4]">
            G
          </span>
        ) : (
          <LogInIcon className="size-4" />
        )}
        {loading ? dict.auth.signingIn : mode === "sigmaris" ? "Googleでログイン" : dict.auth.signIn}
      </button>
      {error ? <p className={mode === "sigmaris" ? "text-center text-xs text-red-300" : "text-xs text-red-600"}>{error}</p> : null}
    </div>
  );
}
