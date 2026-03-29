import { AppShell } from "@/components/app-shell";
import { CalendarBoard } from "@/components/calendar-board";
import { listEventsForMonthForUser } from "@/lib/events";
import { getDictionary } from "@/lib/i18n";
import { readUserLocale } from "@/lib/profile-settings";
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
  const locale = await readUserLocale(user.id);
  const dict = getDictionary(locale);
  const monthForQuery =
    selectedMonth ??
    new Intl.DateTimeFormat("sv-SE", {
      timeZone: "Asia/Tokyo",
      year: "numeric",
      month: "2-digit",
    }).format(new Date());
  const events = await listEventsForMonthForUser(user.id, monthForQuery);

  return (
    <AppShell
      locale={locale}
      title={dict.shell.calendarTitle}
      description={dict.shell.calendarDescription}
      badge={dict.shell.calendarBadge}
    >
      <CalendarBoard locale={locale} month={monthForQuery} events={events} />
    </AppShell>
  );
}
