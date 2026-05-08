// 役割: ユーザー設定画面を表示するNext.jsページ。

import { AppShell } from "@/components/app-shell";
import {
  AiTonePreferencePanel,
  ArrivalLeadMinutesPanel,
  BillingPanel,
  GoogleCalendarSyncPanel,
  IntegrationStatusPanel,
  LanguagePreferencePanel,
  PreferredTravelModePanel,
  SavedLocationsPanel,
  ThemePreferencePanel,
} from "@/components/settings";
import { hasGoogleCalendarWriteConfig } from "@/lib/google/calendar";
import { hasGoogleMapsConfig } from "@/lib/google/maps";
import { hasGoogleSheetsReadConfig } from "@/lib/google/sheets";
import { getDictionary } from "@/lib/i18n";
import { readBillingStatus } from "@/lib/billing";
import { readSettingsPageSettings } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";
import { hasSupabaseConfig } from "@/lib/supabase/client";

type SettingsPageProps = {
  searchParams?: Promise<{
    authError?: string;
  }>;
};

export default async function SettingsPage({ searchParams }: SettingsPageProps) {
  const user = await requireUser("/settings");
  const [resolved, settings, billing] = await Promise.all([
    searchParams ? searchParams : Promise.resolve(undefined),
    readSettingsPageSettings(user.id),
    readBillingStatus(user.id),
  ]);
  const {
    locale,
    theme,
    calendarSyncEnabled,
    aiTone,
    preferredTravelMode,
    arrivalLeadMinutes,
  } = settings;
  const dict = getDictionary(locale);
  const sheetsReady = hasGoogleSheetsReadConfig();
  const calendarReady = hasGoogleCalendarWriteConfig();
  const mapsReady = hasGoogleMapsConfig();
  const supabaseReady = hasSupabaseConfig();

  return (
    <AppShell
      locale={locale}
      title={dict.shell.settingsTitle}
      description={dict.shell.settingsDescription}
      badge={dict.shell.settingsBadge}
      theme={theme}
    >
      <div className="settings-page grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <BillingPanel initialBilling={billing} />

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

        <IntegrationStatusPanel
          backendApiLabel="ShiftPilotAI Backend API"
          backendChatLabel="ShiftPilotAI Backend Chat Tools"
          calendarLabel="Google Calendar API"
          calendarReady={calendarReady}
          integrationsLabel={dict.settings.integrations}
          loadingLabel={dict.common.loading}
          mapsLabel="Google Maps Routes API"
          mapsReady={mapsReady}
          missingLabel={dict.settings.statusMissing}
          readyLabel={dict.settings.statusReady}
          sheetsLabel="Google Sheets API"
          sheetsReady={sheetsReady}
          supabaseLabel="Supabase Authentication"
          supabaseReady={supabaseReady}
        />

        {resolved?.authError ? (
          <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-7 text-red-700">
            {resolved.authError}
          </p>
        ) : null}
      </div>
    </AppShell>
  );
}
