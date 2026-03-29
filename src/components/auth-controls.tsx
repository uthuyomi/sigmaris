"use client";

import { createClient, hasSupabaseConfig } from "@/lib/supabase/client";
import type { User } from "@supabase/supabase-js";
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
  mode?: "compact" | "hero";
};

export function AuthControls({
  redirectPath,
  mode = "compact",
}: AuthControlsProps) {
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

    return () => {
      subscription.unsubscribe();
    };
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

      if (error) {
        throw error;
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "Google 接続に失敗しました。");
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
      await fetch("/auth/signout", {
        method: "POST",
      });
      window.location.assign("/");
    } catch (error) {
      setError(error instanceof Error ? error.message : "ログアウトに失敗しました。");
      setLoading(false);
    }
  };

  if (!available) {
    return (
      <div className="rounded-full border border-stone-900/10 bg-white px-4 py-2 text-sm text-stone-500">
        Supabase 未設定
      </div>
    );
  }

  if (user) {
    return (
      <div className="flex flex-col items-start gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="rounded-full border border-stone-900/10 bg-white px-4 py-2 text-sm text-stone-700">
            {user.email ?? "Google ログイン中"}
          </div>
          <button
            type="button"
            onClick={signOut}
            disabled={loading}
            className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50 disabled:opacity-50"
          >
            ログアウト
          </button>
        </div>
        {error ? <p className="text-xs text-red-600">{error}</p> : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <button
        type="button"
        onClick={signInWithGoogle}
        disabled={loading}
        className={
          mode === "hero"
            ? "rounded-full bg-stone-900 px-6 py-3 text-base font-semibold text-stone-50 disabled:opacity-50"
            : "rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50 disabled:opacity-50"
        }
      >
        {loading ? "接続中..." : "Google でログイン"}
      </button>
      {error ? <p className="text-xs text-red-600">{error}</p> : null}
    </div>
  );
}
