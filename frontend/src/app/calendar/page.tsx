// 役割: カレンダー画面を表示するNext.jsページ。

import { AppShell } from "@/components/app-shell";
import { CalendarBoard } from "@/components/calendar-board";
import { CalendarLiveSync } from "@/components/calendar-live-sync";
import { listEventsForMonthForUser } from "@/lib/events";
import { getDictionary } from "@/lib/i18n";
import { readAppTheme, readGoogleCalendarSyncEnabled, readUserLocale } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";

type CalendarPageProps = {
  searchParams?: Promise<{
    month?: string;
  }>;
};

export default async function CalendarPage({ searchParams }: CalendarPageProps) {
  const params = searchParams ? await searchParams : undefined;
  const selectedMonth = params?.month;
  const user = await requireUser("/calendar");
  const monthForQuery =
    selectedMonth ??
    new Intl.DateTimeFormat("sv-SE", {
      timeZone: "Asia/Tokyo",
      year: "numeric",
      month: "2-digit",
    }).format(new Date());
  const [locale, theme, googleCalendarSyncEnabled, events] = await Promise.all([
    readUserLocale(user.id),
    readAppTheme(user.id),
    readGoogleCalendarSyncEnabled(user.id),
    listEventsForMonthForUser(user.id, monthForQuery),
  ]);
  const dict = getDictionary(locale);

  return (
    <AppShell
      locale={locale}
      title={dict.shell.calendarTitle}
      description={dict.shell.calendarDescription}
      badge={dict.shell.calendarBadge}
      theme={theme}
    >
      <CalendarLiveSync userId={user.id} syncEnabled={googleCalendarSyncEnabled} />
      <CalendarBoard locale={locale} month={monthForQuery} events={events} />
    </AppShell>
  );
}
