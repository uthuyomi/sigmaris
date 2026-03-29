import { AppShell } from "@/components/app-shell";
import { GoogleCalendarSyncPanel } from "@/components/google-calendar-sync-panel";
import { LanguagePreferencePanel } from "@/components/language-preference-panel";
import { hasGoogleCalendarWriteConfig } from "@/lib/google/calendar";
import { hasGoogleMapsConfig } from "@/lib/google/maps";
import { hasGoogleSheetsReadConfig } from "@/lib/google/sheets";
import { getDictionary } from "@/lib/i18n";
import {
  readGoogleCalendarSyncEnabled,
  readUserLocale,
} from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";
import { hasSupabaseConfig } from "@/lib/supabase/client";

const envLabels = [
  "NEXT_PUBLIC_SUPABASE_URL",
  "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
  "GOOGLE_CLIENT_ID",
  "GOOGLE_CLIENT_SECRET",
  "GOOGLE_REDIRECT_URI",
  "GOOGLE_CALENDAR_ID",
  "GOOGLE_MAPS_API_KEY",
  "HOME_ADDRESS",
  "NEXT_PUBLIC_HOME_ADDRESS",
];

type SettingsPageProps = {
  searchParams?: Promise<{
    authError?: string;
  }>;
};

export default async function SettingsPage({ searchParams }: SettingsPageProps) {
  const user = await requireUser("/settings");
  const locale = await readUserLocale(user.id);
  const dict = getDictionary(locale);
  const resolved = searchParams ? await searchParams : undefined;
  const sheetsReady = hasGoogleSheetsReadConfig();
  const calendarReady = hasGoogleCalendarWriteConfig();
  const mapsReady = hasGoogleMapsConfig();
  const supabaseReady = hasSupabaseConfig();
  const calendarSyncEnabled = await readGoogleCalendarSyncEnabled(user.id);

  return (
    <AppShell
      locale={locale}
      title={dict.shell.settingsTitle}
      description={dict.shell.settingsDescription}
      badge={dict.shell.settingsBadge}
    >
      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <LanguagePreferencePanel
          currentLocale={locale}
          title={dict.settings.language}
          hint={dict.settings.languageHint}
          saveLabel={dict.common.save}
        />

        <GoogleCalendarSyncPanel
          locale={locale}
          initialEnabled={calendarSyncEnabled}
          calendarReady={calendarReady}
        />

        <section className="rounded-[30px] border border-stone-900/10 bg-white/85 p-5 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-500">{dict.settings.integrations}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {[
              { name: "Supabase", ready: supabaseReady },
              { name: "Sheets", ready: sheetsReady },
              { name: "Calendar", ready: calendarReady },
              { name: "Maps", ready: mapsReady },
            ].map((item) => (
              <div
                key={item.name}
                className="rounded-[24px] border border-stone-900/10 bg-stone-50 px-4 py-4"
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

        <section className="rounded-[30px] border border-stone-900/10 bg-stone-900 p-5 text-stone-50">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-400">{dict.settings.environment}</p>
          <ul className="mt-4 grid gap-2 text-sm leading-7 text-stone-300">
            {envLabels.map((label) => (
              <li key={label} className="rounded-2xl border border-white/10 px-3 py-2">
                {label}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </AppShell>
  );
}
