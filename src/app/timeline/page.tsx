import { AppShell } from "@/components/app-shell";
import { TimelineBoard } from "@/components/timeline-board";
import { listEventsForDateForUser } from "@/lib/events";
import { formatJapaneseDate } from "@/lib/mock-schedule";
import { getDictionary } from "@/lib/i18n";
import { readUserLocale } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";

type TimelinePageProps = {
  searchParams?: Promise<{
    date?: string;
  }>;
};

export default async function TimelinePage({ searchParams }: TimelinePageProps) {
  const params = searchParams ? await searchParams : undefined;
  const selectedDate = params?.date ?? "2026-03-27";
  const user = await requireUser(`/timeline?date=${selectedDate}`);
  const locale = await readUserLocale(user.id);
  const dict = getDictionary(locale);
  const events = await listEventsForDateForUser(user.id, selectedDate);

  return (
    <AppShell
      locale={locale}
      title={dict.shell.timelineTitle}
      description={`${formatJapaneseDate(selectedDate)} · ${dict.shell.timelineDescription}`}
      badge={dict.shell.timelineBadge}
    >
      <TimelineBoard locale={locale} selectedDate={selectedDate} events={events} />
    </AppShell>
  );
}
