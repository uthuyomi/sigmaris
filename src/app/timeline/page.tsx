import { AppShell } from "@/components/app-shell";
import { TimelineBoard } from "@/components/timeline-board";
import { formatJapaneseDate } from "@/lib/mock-schedule";
import { requireUser } from "@/lib/supabase/auth";

type TimelinePageProps = {
  searchParams?: Promise<{
    date?: string;
  }>;
};

export default async function TimelinePage({ searchParams }: TimelinePageProps) {
  const params = searchParams ? await searchParams : undefined;
  const selectedDate = params?.date ?? "2026-03-27";
  await requireUser(`/timeline?date=${selectedDate}`);

  return (
    <AppShell
      title="タイムラインで時間調整"
      description={`${formatJapaneseDate(selectedDate)} の 24 時間タイムライン。カレンダーで日付を選んでから、ここで細かい時間を詰める。`}
      badge="カレンダー連携"
    >
      <TimelineBoard selectedDate={selectedDate} />
    </AppShell>
  );
}
