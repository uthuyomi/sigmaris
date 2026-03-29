import { AppShell } from "@/components/app-shell";
import { hasGoogleCalendarWriteConfig } from "@/lib/google/calendar";
import { hasGoogleMapsConfig } from "@/lib/google/maps";
import { hasGoogleSheetsReadConfig } from "@/lib/google/sheets";
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
  await requireUser("/settings");

  const resolved = searchParams ? await searchParams : undefined;
  const sheetsReady = hasGoogleSheetsReadConfig();
  const calendarReady = hasGoogleCalendarWriteConfig();
  const mapsReady = hasGoogleMapsConfig();
  const supabaseReady = hasSupabaseConfig();

  return (
    <AppShell
      title="設定"
      description="認証、外部連携、移動計画まわりの初期値をここで確認する。"
      badge="Google 連携状況"
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-[32px] border border-stone-900/10 bg-white/75 p-5 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Account</p>
          <h2 className="mt-2 text-lg font-semibold text-stone-900">認証方針</h2>
          <ul className="mt-3 space-y-3 text-sm leading-7 text-stone-700">
            <li>初期ログインは Google OAuth 一本</li>
            <li>認証基盤は Supabase Auth</li>
            <li>Google Calendar と Sheets の権限をまとめて扱う</li>
          </ul>
          {resolved?.authError ? (
            <p className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-7 text-red-700">
              認証エラー: {resolved.authError}
            </p>
          ) : null}
        </section>

        <section className="rounded-[32px] border border-stone-900/10 bg-stone-900 p-5 text-stone-50">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-400">Schedule defaults</p>
          <ul className="mt-3 space-y-3 text-sm leading-7 text-stone-300">
            <li>デフォルト粒度: 10分</li>
            <li>切り替え候補: 5 / 10 / 15 / 30 / 60分</li>
            <li>カレンダーで日付を決めてからタイムラインで調整</li>
          </ul>
        </section>

        <section className="rounded-[32px] border border-stone-900/10 bg-white/75 p-5 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur lg:col-span-2">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Integration status</p>
          <div className="mt-4 grid gap-4 md:grid-cols-4">
            <div className="rounded-[28px] border border-stone-900/10 bg-stone-50 p-4">
              <p className="text-sm font-semibold text-stone-900">Supabase Auth</p>
              <p className="mt-2 text-sm text-stone-600">
                状態: {supabaseReady ? "設定済み" : "未設定"}
              </p>
            </div>
            <div className="rounded-[28px] border border-stone-900/10 bg-stone-50 p-4">
              <p className="text-sm font-semibold text-stone-900">Google Sheets 読み取り</p>
              <p className="mt-2 text-sm text-stone-600">
                状態: {sheetsReady ? "設定済み" : "未設定"}
              </p>
            </div>
            <div className="rounded-[28px] border border-stone-900/10 bg-stone-50 p-4">
              <p className="text-sm font-semibold text-stone-900">Google Calendar 書き込み</p>
              <p className="mt-2 text-sm text-stone-600">
                状態: {calendarReady ? "設定済み" : "未設定"}
              </p>
            </div>
            <div className="rounded-[28px] border border-stone-900/10 bg-stone-50 p-4">
              <p className="text-sm font-semibold text-stone-900">Google Maps 移動計画</p>
              <p className="mt-2 text-sm text-stone-600">
                状態: {mapsReady ? "設定済み" : "未設定"}
              </p>
            </div>
          </div>

          <div className="mt-4 rounded-[28px] border border-stone-900/10 bg-stone-50 p-4">
            <p className="text-sm font-semibold text-stone-900">必要な環境変数</p>
            <ul className="mt-3 space-y-2 text-sm leading-7 text-stone-700">
              {envLabels.map((label) => (
                <li key={label}>{label}</li>
              ))}
            </ul>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
