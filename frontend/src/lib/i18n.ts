// Public i18n helpers used by pages and components.
import { dictionaries } from "@/i18n/dictionaries";
import { defaultLocale, supportedLocales, type AppLocale } from "@/i18n/types";
import type { Dictionary } from "@/i18n/types";

export { defaultLocale, supportedLocales };
export type { AppLocale, Dictionary };

export const normalizeLocale = (value?: string | null): AppLocale => {
  if (!value) return defaultLocale;
  const matched = supportedLocales.find((locale) => locale.toLowerCase() === value.toLowerCase());
  return matched ?? defaultLocale;
};

export const getDictionary = (locale?: string | null) => dictionaries[normalizeLocale(locale)];

export const formatLocaleName = (locale: AppLocale, displayLocale: AppLocale) => {
  try {
    const names = new Intl.DisplayNames([displayLocale], { type: "language" });
    return names.of(locale) ?? names.of(locale.split("-")[0]) ?? locale;
  } catch {
    return locale;
  }
};
