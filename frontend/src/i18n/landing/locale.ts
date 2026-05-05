import { defaultLocale, supportedLocales, type AppLocale } from "@/i18n/types";

const localeAliases: Partial<Record<string, AppLocale>> = {
  "zh-hans": "zh-CN",
  "zh-cn": "zh-CN",
  "zh-sg": "zh-CN",
  zh: "zh-CN",
  "zh-hant": "zh-TW",
  "zh-tw": "zh-TW",
  "zh-hk": "zh-TW",
  pt: "pt-BR",
  "pt-br": "pt-BR",
};

export const resolveLandingLocale = (acceptLanguage: string | null): AppLocale => {
  if (!acceptLanguage) return defaultLocale;

  const requested = acceptLanguage
    .split(",")
    .map((part) => part.trim().split(";")[0]?.toLowerCase())
    .filter(Boolean);

  for (const locale of requested) {
    const alias = localeAliases[locale];
    if (alias) return alias;

    const exact = supportedLocales.find((supported) => supported.toLowerCase() === locale);
    if (exact) return exact;

    const base = locale.split("-")[0];
    const baseAlias = localeAliases[base];
    if (baseAlias) return baseAlias;

    const matchedBase = supportedLocales.find((supported) => supported.toLowerCase() === base);
    if (matchedBase) return matchedBase;
  }

  return defaultLocale;
};

