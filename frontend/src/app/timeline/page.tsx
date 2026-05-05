// 役割: タイムライン画面を表示するNext.jsページ。

import { AppShell } from "@/components/app-shell";
import { TimelineBoard } from "@/components/timeline-board";
import { listEventsForDateForUser } from "@/lib/events";
import { formatJapaneseDate } from "@/lib/mock-schedule";
import { getDictionary } from "@/lib/i18n";
import { readShellSettings } from "@/lib/profile-settings";
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
  const [settings, events] = await Promise.all([
    readShellSettings(user.id),
    listEventsForDateForUser(user.id, selectedDate),
  ]);
  const { locale, theme } = settings;
  const dict = getDictionary(locale);

  return (
    <AppShell
      locale={locale}
      title={dict.shell.timelineTitle}
      description={`${formatJapaneseDate(selectedDate)} · ${dict.shell.timelineDescription}`}
      badge={dict.shell.timelineBadge}
      theme={theme}
    >
      <TimelineBoard locale={locale} selectedDate={selectedDate} events={events} />
    </AppShell>
  );
}
