"use client";

import { CheckIcon, MoonIcon, SunIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import type { AppTheme } from "@/lib/profile-settings";

type ThemePreferencePanelProps = {
  currentTheme: AppTheme;
};

const themeOptions: Array<{
  value: AppTheme;
  label: string;
  Icon: typeof SunIcon;
}> = [
  { value: "light", label: "Light", Icon: SunIcon },
  { value: "dark", label: "Dark", Icon: MoonIcon },
];

const applyThemeToDocument = (theme: AppTheme) => {
  document.documentElement.classList.toggle("dark", theme === "dark");
};

export function ThemePreferencePanel({ currentTheme }: ThemePreferencePanelProps) {
  const router = useRouter();
  const [selectedTheme, setSelectedTheme] = useState<AppTheme>(currentTheme);
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    applyThemeToDocument(selectedTheme);
  }, [selectedTheme]);

  const save = (theme: AppTheme) => {
    setSelectedTheme(theme);
    applyThemeToDocument(theme);

    if (theme === currentTheme) {
      setMessage(null);
      return;
    }

    startTransition(async () => {
      setMessage(null);
      const response = await fetch("/api/settings/theme", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ theme }),
      });

      if (!response.ok) {
        setMessage("Failed");
        return;
      }

      setMessage("Saved");
      router.refresh();
    });
  };

  return (
    <section className="rounded-2xl border border-stone-900/10 bg-white p-4 shadow-sm dark:border-white/10 dark:bg-[#2f2f2f]">
      <div className="flex items-center gap-3">
        <div className="inline-flex size-10 items-center justify-center rounded-xl bg-stone-950 text-white dark:bg-white dark:text-stone-950">
          <MoonIcon className="size-5" />
        </div>
        <div>
          <h2 className="text-base font-semibold text-stone-950 dark:text-stone-50">Theme</h2>
          <p className="text-xs text-stone-500 dark:text-stone-400">Light / Dark</p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        {themeOptions.map(({ value, label, Icon }) => {
          const active = value === selectedTheme;

          return (
            <button
              key={value}
              type="button"
              onClick={() => save(value)}
              disabled={isPending}
              className={`flex min-h-14 items-center justify-between rounded-xl border px-3 text-left transition disabled:opacity-60 ${
                active
                  ? "border-stone-950 bg-stone-950 text-white dark:border-white/20 dark:bg-white/12 dark:text-white"
                  : "border-stone-900/10 bg-stone-50 text-stone-800 hover:bg-stone-100 dark:border-white/10 dark:bg-white/6 dark:text-stone-200 dark:hover:bg-white/10"
              }`}
            >
              <span className="inline-flex items-center gap-2 text-sm font-medium">
                <Icon className="size-4" />
                {label}
              </span>
              {active ? <CheckIcon className="size-4" /> : null}
            </button>
          );
        })}
      </div>

      {message ? <p className="mt-3 text-xs text-stone-500 dark:text-stone-400">{message}</p> : null}
    </section>
  );
}
