import { createClient } from "@/lib/supabase/server";
import { defaultLocale, normalizeLocale, type AppLocale } from "@/lib/i18n";

const isMissingLocaleColumnError = (error: { code?: string; message?: string } | null) => {
  if (!error) return false;
  return (
    error.code === "42703" ||
    error.message?.includes("column profiles.locale does not exist") ||
    error.message?.includes("column \"locale\" does not exist")
  );
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
