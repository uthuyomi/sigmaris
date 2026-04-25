"use client";
// 役割: 表示言語を選択して保存するReactクライアントコンポーネント。


import { CheckIcon, ChevronDownIcon, LanguagesIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";
import { formatLocaleName, supportedLocales, type AppLocale } from "@/lib/i18n";

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
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const selectedNativeName = useMemo(
    () => formatLocaleName(selectedLocale, selectedLocale),
    [selectedLocale],
  );

  const save = (locale: AppLocale) => {
    setSelectedLocale(locale);
    setOpen(false);

    if (locale === currentLocale) {
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
        body: JSON.stringify({ locale }),
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
      <div className="flex items-start gap-4">
        <div className="inline-flex size-11 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
          <LanguagesIcon className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold text-stone-900">{title}</h2>
          <p className="mt-2 text-sm leading-7 text-stone-600">{hint}</p>
        </div>
      </div>

      <div className="mt-5">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex w-full items-center justify-between rounded-[24px] border border-stone-900/10 bg-stone-50 px-4 py-4 text-left transition hover:bg-white"
          aria-expanded={open}
        >
          <div>
            <p className="text-sm font-semibold text-stone-900">{selectedNativeName}</p>
            <p className="mt-1 text-xs text-stone-500">
              {selectedLocale} / {formatLocaleName(selectedLocale, currentLocale)}
            </p>
          </div>
          <ChevronDownIcon className={`size-5 text-stone-500 transition ${open ? "rotate-180" : ""}`} />
        </button>

        {open ? (
          <div className="mt-3 max-h-[22rem] space-y-2 overflow-y-auto pr-1">
            {supportedLocales.map((locale) => {
              const active = locale === selectedLocale;
              const nativeName = formatLocaleName(locale, locale);
              const currentName = formatLocaleName(locale, currentLocale);

              return (
                <button
                  key={locale}
                  type="button"
                  onClick={() => save(locale)}
                  disabled={isPending}
                  className={`flex w-full items-center justify-between rounded-[22px] border px-4 py-3 text-left transition ${
                    active
                      ? "border-stone-900 bg-stone-900 text-stone-50"
                      : "border-stone-900/10 bg-stone-50 text-stone-900 hover:bg-white"
                  }`}
                >
                  <div>
                    <p className="text-sm font-semibold">{nativeName}</p>
                    <p className={`mt-1 text-xs ${active ? "text-stone-300" : "text-stone-500"}`}>
                      {locale} / {currentName}
                    </p>
                  </div>
                  {active ? <CheckIcon className="size-4" /> : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>

      {message ? <p className="mt-3 text-sm text-stone-500">{message}</p> : null}
    </section>
  );
}
