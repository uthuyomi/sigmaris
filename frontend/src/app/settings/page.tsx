// 役割: ユーザー設定画面を表示するNext.jsページ。

import { AppShell } from "@/components/app-shell";
import { AiTonePreferencePanel } from "@/components/ai-tone-preference-panel";
import { ArrivalLeadMinutesPanel } from "@/components/arrival-lead-minutes-panel";
import { GoogleCalendarSyncPanel } from "@/components/google-calendar-sync-panel";
import { LanguagePreferencePanel } from "@/components/language-preference-panel";
import { PreferredTravelModePanel } from "@/components/preferred-travel-mode-panel";
import { SavedLocationsPanel } from "@/components/saved-locations-panel";
import { ThemePreferencePanel } from "@/components/theme-preference-panel";
import { readBackendChatCapabilities } from "@/lib/backend/chat";
import { hasGoogleCalendarWriteConfig } from "@/lib/google/calendar";
import { hasGoogleMapsConfig } from "@/lib/google/maps";
import { hasGoogleSheetsReadConfig } from "@/lib/google/sheets";
import { readBackendHealth } from "@/lib/backend/health";
import { getDictionary } from "@/lib/i18n";
import {
  readAiTone,
  readAppTheme,
  readArrivalLeadMinutes,
  readGoogleCalendarSyncEnabled,
  readPreferredTravelMode,
  readUserLocale,
} from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";
import { hasSupabaseConfig } from "@/lib/supabase/client";

type SettingsPageProps = {
  searchParams?: Promise<{
    authError?: string;
  }>;
};

export default async function SettingsPage({ searchParams }: SettingsPageProps) {
  const user = await requireUser("/settings");
  const locale = await readUserLocale(user.id);
  const theme = await readAppTheme(user.id);
  const dict = getDictionary(locale);
  const resolved = searchParams ? await searchParams : undefined;
  const sheetsReady = hasGoogleSheetsReadConfig();
  const calendarReady = hasGoogleCalendarWriteConfig();
  const mapsReady = hasGoogleMapsConfig();
  const supabaseReady = hasSupabaseConfig();
  const calendarSyncEnabled = await readGoogleCalendarSyncEnabled(user.id);
  const aiTone = await readAiTone(user.id);
  const preferredTravelMode = await readPreferredTravelMode(user.id);
  const arrivalLeadMinutes = await readArrivalLeadMinutes(user.id);
  const backendHealth = await readBackendHealth();
  const backendChat = await readBackendChatCapabilities();

  return (
    <AppShell
      locale={locale}
      title={dict.shell.settingsTitle}
      description={dict.shell.settingsDescription}
      badge={dict.shell.settingsBadge}
      theme={theme}
    >
      <div className="settings-page grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <ThemePreferencePanel currentTheme={theme} />

        <LanguagePreferencePanel
          currentLocale={locale}
          title={dict.settings.language}
          hint={dict.settings.languageHint}
          saveLabel={dict.common.save}
        />

        <AiTonePreferencePanel currentTone={aiTone} />

        <PreferredTravelModePanel currentTravelMode={preferredTravelMode} />

        <ArrivalLeadMinutesPanel currentMinutes={arrivalLeadMinutes} />

        <GoogleCalendarSyncPanel
          locale={locale}
          initialEnabled={calendarSyncEnabled}
          calendarReady={calendarReady}
        />

        <SavedLocationsPanel />

        <section className="rounded-2xl border border-stone-900/10 bg-white p-5 shadow-sm dark:border-white/10 dark:bg-[#2f2f2f]">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-500 dark:text-stone-400">{dict.settings.integrations}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {[
              { name: "ShiftPilotAI Backend API", ready: backendHealth.ready },
              { name: "ShiftPilotAI Backend Chat Tools", ready: backendChat.ready },
              { name: "Supabase Authentication", ready: supabaseReady },
              { name: "Google Sheets API", ready: sheetsReady },
              { name: "Google Calendar API", ready: calendarReady },
              { name: "Google Maps Routes API", ready: mapsReady },
            ].map((item) => (
              <div
                key={item.name}
                className="rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-4 dark:border-white/10 dark:bg-white/6"
              >
                <p className="text-sm font-semibold text-stone-900">{item.name}</p>
                <p className="mt-2 text-sm text-stone-600">
                  {item.ready ? dict.settings.statusReady : dict.settings.statusMissing}
                </p>
              </div>
            ))}
          </div>
          {resolved?.authError ? (
            <p className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-7 text-red-700">
              {resolved.authError}
            </p>
          ) : null}
        </section>
      </div>
    </AppShell>
  );
}
