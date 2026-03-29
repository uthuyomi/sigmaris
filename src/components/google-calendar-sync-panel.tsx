"use client";

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
  const [isPending, startTransition] = useTransition();

  const runSync = async () => {
    const syncRes = await fetch("/api/sync/google-calendar", {
      method: "POST",
    });

    const syncData = await syncRes.json();
    if (!syncRes.ok) {
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

    startTransition(async () => {
      try {
        await runSync();
      } catch (syncError) {
        setError(syncError instanceof Error ? syncError.message : dict.settings.syncError);
      }
    });
  };

  return (
    <div className="rounded-[30px] border border-stone-900/10 bg-stone-50 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="inline-flex size-11 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
            <ArrowUpDownIcon className="size-5" />
          </div>
          <h2 className="mt-4 text-lg font-semibold text-stone-900">{dict.settings.syncTitle}</h2>
          <p className="mt-2 text-sm leading-7 text-stone-600">{dict.settings.syncBody}</p>
        </div>

        <button
          type="button"
          onClick={toggle}
          disabled={isPending || !calendarReady}
          aria-pressed={enabled}
          className={`relative inline-flex h-9 w-16 shrink-0 items-center rounded-full transition ${
            enabled ? "bg-stone-900" : "bg-stone-300"
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
        <span className={enabled ? "font-medium text-stone-900" : "text-stone-500"}>
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
          className="inline-flex items-center gap-2 rounded-full bg-stone-900 px-4 py-2 font-medium text-stone-50 transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-300"
        >
          <RefreshCcwIcon className="size-4" />
          {dict.common.syncNow}
        </button>
      </div>

      {message ? (
        <p className="mt-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm leading-7 text-emerald-700">
          {message}
        </p>
      ) : null}

      {error ? (
        <p className="mt-3 rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm leading-7 text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}
