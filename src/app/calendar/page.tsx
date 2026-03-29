import { AppShell } from "@/components/app-shell";
import { CalendarBoard } from "@/components/calendar-board";
import { requireUser } from "@/lib/supabase/auth";

export default async function CalendarPage() {
  await requireUser("/calendar");

  return (
    <AppShell
      title="カレンダーで日付確認"
      description="月全体で予定密度を見ながら、気になる日を選んでその日の 24 時間タイムラインへ降りる。"
      badge="月表示"
    >
      <CalendarBoard />
    </AppShell>
  );
}
