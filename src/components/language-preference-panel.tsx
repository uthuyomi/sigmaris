"use client";

import { GlobeIcon, LanguagesIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import {
  formatLocaleName,
  supportedLocales,
  type AppLocale,
} from "@/lib/i18n";

type LanguagePreferencePanelProps = {
  currentLocale: AppLocale;
  title: string;
  hint: string;
  saveLabel: string;
};

export function LanguagePreferencePanel({
  currentLocale,
  title,
  hint,
  saveLabel,
}: LanguagePreferencePanelProps) {
  const router = useRouter();
  const [selectedLocale, setSelectedLocale] = useState<AppLocale>(currentLocale);
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const save = () => {
    if (selectedLocale === currentLocale) {
      setMessage(null);
      return;
    }

    startTransition(async () => {
      setMessage(null);
      const response = await fetch("/api/settings/language", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ locale: selectedLocale }),
      });

      if (!response.ok) {
        setMessage("Failed");
        return;
      }

      setMessage(saveLabel);
      router.refresh();
    });
  };

  return (
    <section className="rounded-[30px] border border-stone-900/10 bg-white/85 p-5 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="inline-flex size-11 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
            <LanguagesIcon className="size-5" />
          </div>
          <h2 className="mt-4 text-lg font-semibold text-stone-900">{title}</h2>
          <p className="mt-2 text-sm leading-7 text-stone-600">{hint}</p>
        </div>
        <button
          type="button"
          onClick={save}
          disabled={isPending || selectedLocale === currentLocale}
          className="inline-flex size-11 items-center justify-center rounded-full bg-stone-900 text-stone-50 transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-300"
          aria-label={saveLabel}
        >
          <GlobeIcon className="size-5" />
        </button>
      </div>

      <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {supportedLocales.map((locale) => {
          const active = locale === selectedLocale;
          const nativeName = formatLocaleName(locale, locale);
          const currentName = formatLocaleName(locale, currentLocale);

          return (
            <button
              key={locale}
              type="button"
              onClick={() => setSelectedLocale(locale)}
              className={`rounded-[22px] border px-4 py-3 text-left transition ${
                active
                  ? "border-stone-900 bg-stone-900 text-stone-50"
                  : "border-stone-900/10 bg-stone-50 text-stone-900 hover:bg-white"
              }`}
            >
              <p className="text-sm font-semibold">{nativeName}</p>
              <p className={`mt-1 text-xs ${active ? "text-stone-300" : "text-stone-500"}`}>
                {locale} · {currentName}
              </p>
            </button>
          );
        })}
      </div>

      {message ? <p className="mt-3 text-sm text-stone-500">{message}</p> : null}
    </section>
  );
}
