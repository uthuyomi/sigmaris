import type { AppLocale, Dictionary } from "@/i18n/types";
import { ja } from "@/i18n/locales/ja";
import { en } from "@/i18n/locales/en";
import { ko } from "@/i18n/locales/ko";
import { zhCN } from "@/i18n/locales/zh-CN";
import { zhTW } from "@/i18n/locales/zh-TW";
import { es } from "@/i18n/locales/es";
import { fr } from "@/i18n/locales/fr";
import { de } from "@/i18n/locales/de";
import { ptBR } from "@/i18n/locales/pt-BR";
import { it } from "@/i18n/locales/it";
import { id } from "@/i18n/locales/id";
import { th } from "@/i18n/locales/th";
import { vi } from "@/i18n/locales/vi";

export const dictionaries: Record<AppLocale, Dictionary> = {
  ja: ja,
  en: en,
  ko: ko,
  "zh-CN": zhCN,
  "zh-TW": zhTW,
  es: es,
  fr: fr,
  de: de,
  "pt-BR": ptBR,
  it: it,
  id: id,
  th: th,
  vi: vi,
};
