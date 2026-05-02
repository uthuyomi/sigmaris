// 役割: ユーザーのプロフィール設定を読み書きする処理をまとめる。

import { createClient } from "@/lib/supabase/server";
import { defaultLocale, normalizeLocale, type AppLocale } from "@/lib/i18n";

export const supportedAiTones = ["default", "friendly", "concise", "direct"] as const;
export type AiTone = (typeof supportedAiTones)[number];
const defaultAiTone: AiTone = "default";
export const supportedAppThemes = ["light", "dark"] as const;
export type AppTheme = (typeof supportedAppThemes)[number];
export const defaultAppTheme: AppTheme = "light";
export const supportedPreferredTravelModes = ["bicycle", "car", "walk"] as const;
export type PreferredTravelMode = (typeof supportedPreferredTravelModes)[number];
const defaultPreferredTravelMode: PreferredTravelMode = "car";
export const defaultArrivalLeadMinutes = 10;

const isMissingLocaleColumnError = (error: { code?: string; message?: string } | null) => {
  if (!error) return false;
  return (
    error.code === "42703" ||
    error.message?.includes("column profiles.locale does not exist") ||
    error.message?.includes("column \"locale\" does not exist")
  );
};

const isMissingAiToneColumnError = (error: { code?: string; message?: string } | null) => {
  if (!error) return false;
  return (
    error.code === "42703" ||
    error.message?.includes("column profiles.ai_tone does not exist") ||
    error.message?.includes("column \"ai_tone\" does not exist")
  );
};

const isMissingAppThemeColumnError = (error: { code?: string; message?: string } | null) => {
  if (!error) return false;
  return (
    error.code === "42703" ||
    error.message?.includes("column profiles.app_theme does not exist") ||
    error.message?.includes('column "app_theme" does not exist')
  );
};

const isMissingPreferredTravelModeColumnError = (
  error: { code?: string; message?: string } | null,
) => {
  if (!error) return false;
  return (
    error.code === "42703" ||
    error.message?.includes("column profiles.preferred_travel_mode does not exist") ||
    error.message?.includes('column "preferred_travel_mode" does not exist')
  );
};

const isMissingArrivalLeadMinutesColumnError = (
  error: { code?: string; message?: string } | null,
) => {
  if (!error) return false;
  return (
    error.code === "42703" ||
    error.message?.includes("column profiles.arrival_lead_minutes does not exist") ||
    error.message?.includes('column "arrival_lead_minutes" does not exist')
  );
};

export const normalizeAiTone = (value?: string | null): AiTone => {
  if (!value) return defaultAiTone;
  return supportedAiTones.find((tone) => tone === value) ?? defaultAiTone;
};

export const normalizeAppTheme = (value?: string | null): AppTheme => {
  if (!value) return defaultAppTheme;
  return supportedAppThemes.find((theme) => theme === value) ?? defaultAppTheme;
};

export const normalizePreferredTravelMode = (value?: string | null): PreferredTravelMode => {
  if (!value) return defaultPreferredTravelMode;
  return (
    supportedPreferredTravelModes.find((travelMode) => travelMode === value) ??
    defaultPreferredTravelMode
  );
};

export const normalizeArrivalLeadMinutes = (value?: number | null) => {
  if (typeof value !== "number" || Number.isNaN(value)) return defaultArrivalLeadMinutes;
  return Math.min(180, Math.max(0, Math.round(value)));
};

export const readGoogleCalendarSyncEnabled = async (userId: string) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("profiles")
    .select("google_calendar_sync_enabled")
    .eq("id", userId)
    .single();

  if (error) {
    throw new Error(error.message);
  }

  return Boolean(data?.google_calendar_sync_enabled);
};

export const readAiTone = async (userId: string): Promise<AiTone> => {
  const supabase = await createClient();
  const { data, error } = await supabase.from("profiles").select("ai_tone").eq("id", userId).single();

  if (error) {
    if (isMissingAiToneColumnError(error)) {
      return defaultAiTone;
    }
    throw new Error(error.message);
  }

  return normalizeAiTone(data?.ai_tone ?? defaultAiTone);
};

export const readAppTheme = async (userId: string): Promise<AppTheme> => {
  const supabase = await createClient();
  const { data, error } = await supabase.from("profiles").select("app_theme").eq("id", userId).single();

  if (error) {
    if (isMissingAppThemeColumnError(error)) {
      return defaultAppTheme;
    }
    throw new Error(error.message);
  }

  return normalizeAppTheme(data?.app_theme ?? defaultAppTheme);
};

export const readPreferredTravelMode = async (userId: string): Promise<PreferredTravelMode> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("profiles")
    .select("preferred_travel_mode")
    .eq("id", userId)
    .single();

  if (error) {
    if (isMissingPreferredTravelModeColumnError(error)) {
      return defaultPreferredTravelMode;
    }
    throw new Error(error.message);
  }

  return normalizePreferredTravelMode(
    data?.preferred_travel_mode ?? defaultPreferredTravelMode,
  );
};

export const readArrivalLeadMinutes = async (userId: string): Promise<number> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("profiles")
    .select("arrival_lead_minutes")
    .eq("id", userId)
    .single();

  if (error) {
    if (isMissingArrivalLeadMinutesColumnError(error)) {
      return defaultArrivalLeadMinutes;
    }
    throw new Error(error.message);
  }

  return normalizeArrivalLeadMinutes(data?.arrival_lead_minutes ?? defaultArrivalLeadMinutes);
};

export const readUserLocale = async (userId: string): Promise<AppLocale> => {
  const supabase = await createClient();
  const { data, error } = await supabase.from("profiles").select("locale").eq("id", userId).single();

  if (error) {
    if (isMissingLocaleColumnError(error)) {
      return defaultLocale;
    }
    throw new Error(error.message);
  }

  return normalizeLocale(data?.locale ?? defaultLocale);
};

export const updateUserLocale = async (userId: string, locale: string) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("profiles")
    .update({ locale: normalizeLocale(locale) })
    .eq("id", userId);

  if (error) {
    if (isMissingLocaleColumnError(error)) {
      throw new Error("profiles.locale column is missing. Apply 202603290004_profile_locale.sql first.");
    }
    throw new Error(error.message);
  }
};

export const updateAiTone = async (userId: string, aiTone: string) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("profiles")
    .update({ ai_tone: normalizeAiTone(aiTone) })
    .eq("id", userId);

  if (error) {
    if (isMissingAiToneColumnError(error)) {
      throw new Error("profiles.ai_tone column is missing. Apply the ai tone migration first.");
    }
    throw new Error(error.message);
  }
};

export const updateAppTheme = async (userId: string, appTheme: string) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("profiles")
    .update({ app_theme: normalizeAppTheme(appTheme) })
    .eq("id", userId);

  if (error) {
    if (isMissingAppThemeColumnError(error)) {
      throw new Error("profiles.app_theme column is missing. Apply the app theme migration first.");
    }
    throw new Error(error.message);
  }
};

export const updatePreferredTravelMode = async (userId: string, travelMode: string) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("profiles")
    .update({ preferred_travel_mode: normalizePreferredTravelMode(travelMode) })
    .eq("id", userId);

  if (error) {
    if (isMissingPreferredTravelModeColumnError(error)) {
      throw new Error(
        "profiles.preferred_travel_mode column is missing. Apply the preferred travel mode migration first.",
      );
    }
    throw new Error(error.message);
  }
};

export const updateArrivalLeadMinutes = async (userId: string, minutes: number) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("profiles")
    .update({ arrival_lead_minutes: normalizeArrivalLeadMinutes(minutes) })
    .eq("id", userId);

  if (error) {
    if (isMissingArrivalLeadMinutesColumnError(error)) {
      throw new Error(
        "profiles.arrival_lead_minutes column is missing. Apply the arrival lead minutes migration first.",
      );
    }
    throw new Error(error.message);
  }
};

export const updateGoogleCalendarSyncEnabled = async (userId: string, enabled: boolean) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("profiles")
    .update({ google_calendar_sync_enabled: enabled })
    .eq("id", userId);

  if (error) {
    throw new Error(error.message);
  }
};

export const markGoogleCalendarSyncRun = async (
  userId: string,
  status: string,
  ranAt = new Date().toISOString(),
) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("profiles")
    .update({
      google_calendar_sync_last_status: status,
      google_calendar_sync_last_run_at: ranAt,
    })
    .eq("id", userId);

  if (error) {
    throw new Error(error.message);
  }
};
