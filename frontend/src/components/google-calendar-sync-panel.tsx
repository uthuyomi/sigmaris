"use client";
// 役割: Google Calendar同期設定を表示・保存するReactクライアントコンポーネント。


import { ArrowUpDownIcon, RefreshCcwIcon } from "lucide-react";
import { useState, useTransition } from "react";
import { getDictionary, type AppLocale } from "@/lib/i18n";

type GoogleCalendarSyncPanelProps = {
  locale: AppLocale;
  initialEnabled: boolean;
  calendarReady: boolean;
};

export function GoogleCalendarSyncPanel({
  locale,
  initialEnabled,
  calendarReady,
}: GoogleCalendarSyncPanelProps) {
  const dict = getDictionary(locale);
  const [enabled, setEnabled] = useState(initialEnabled);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [reconnectRequired, setReconnectRequired] = useState(false);
  const [isPending, startTransition] = useTransition();

  const runSync = async () => {
    setReconnectRequired(false);
    const syncRes = await fetch("/api/sync/google-calendar", {
      method: "POST",
    });

    const syncData = await syncRes.json();
    if (!syncRes.ok) {
      setReconnectRequired(Boolean(syncData.reconnectRequired));
      throw new Error(syncData.error ?? dict.settings.syncError);
    }

    setMessage(
      `${dict.settings.syncSuccess} · ${syncData.importedFromGoogle} / ${syncData.exportedToGoogle}`,
    );
  };

  const toggle = () => {
    const next = !enabled;
    setEnabled(next);
    setError(null);
    setMessage(null);
    setReconnectRequired(false);

    startTransition(async () => {
      try {
        const res = await fetch("/api/settings/google-calendar-sync", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ enabled: next }),
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error ?? dict.settings.syncError);
        }

        if (next) {
          await runSync();
        }
      } catch (fetchError) {
        setEnabled(!next);
        setError(fetchError instanceof Error ? fetchError.message : dict.settings.syncError);
      }
    });
  };

  const syncNow = () => {
    setError(null);
    setMessage(null);
    setReconnectRequired(false);

    startTransition(async () => {
      try {
        await runSync();
      } catch (syncError) {
        setError(syncError instanceof Error ? syncError.message : dict.settings.syncError);
      }
    });
  };

  return (
    <div className="rounded-2xl border border-stone-900/10 bg-stone-50 p-4 dark:border-white/10 dark:bg-white/6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="inline-flex size-11 items-center justify-center rounded-xl bg-stone-900 text-stone-50 dark:bg-white dark:text-stone-950">
            <ArrowUpDownIcon className="size-5" />
          </div>
          <h2 className="mt-4 text-lg font-semibold text-stone-900 dark:text-stone-50">{dict.settings.syncTitle}</h2>
          <p className="mt-2 max-w-md text-sm leading-7 text-stone-600 dark:text-stone-400">
            {dict.settings.syncBody}
          </p>
        </div>

        <button
          type="button"
          onClick={toggle}
          disabled={isPending || !calendarReady}
          aria-pressed={enabled}
          className={`relative inline-flex h-9 w-16 shrink-0 items-center rounded-full transition ${
            enabled ? "bg-stone-900 dark:bg-white" : "bg-stone-300 dark:bg-white/20"
          } ${isPending || !calendarReady ? "opacity-70" : ""}`}
        >
          <span
            className={`inline-block size-7 rounded-full bg-white shadow transition ${
              enabled ? "translate-x-8" : "translate-x-1"
            }`}
          />
        </button>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
        <span className={enabled ? "font-medium text-stone-900 dark:text-stone-50" : "text-stone-500 dark:text-stone-400"}>
          {!calendarReady
            ? dict.common.unavailable
            : enabled
              ? dict.common.statusOn
              : dict.settings.syncDisabled}
        </span>

        <button
          type="button"
          onClick={syncNow}
          disabled={!enabled || isPending || !calendarReady}
          className="inline-flex size-10 items-center justify-center rounded-full bg-stone-900 text-stone-50 transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-300 dark:bg-white dark:text-stone-950 dark:hover:bg-stone-200 dark:disabled:bg-white/20 dark:disabled:text-stone-500"
          aria-label={dict.common.syncNow}
        >
          <RefreshCcwIcon className="size-4" />
        </button>
      </div>

      {message ? (
        <p className="mt-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm leading-7 text-emerald-700">
          {message}
        </p>
      ) : null}

      {error ? (
        <div className="mt-3 rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm leading-7 text-red-700">
          <p>{error}</p>
          {reconnectRequired ? (
            <button
              type="button"
              onClick={async () => {
                await fetch("/auth/signout", { method: "POST" }).catch(() => undefined);
                window.location.assign(`/login?next=${encodeURIComponent("/settings")}`);
              }}
              className="mt-2 rounded-full bg-red-700 px-4 py-2 text-xs font-semibold text-white transition hover:bg-red-800"
            >
              再ログイン
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
