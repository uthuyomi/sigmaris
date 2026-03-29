import { AppShell } from "@/components/app-shell";
import { OverviewDashboard } from "@/components/overview-dashboard";
import { requireUser } from "@/lib/supabase/auth";

export default async function AppHomePage() {
  await requireUser("/app");

  return (
    <AppShell
      title="予定調整のホーム"
      description="チャット、カレンダー、タイムラインを行き来しながら、1日の流れを自然に詰めていく。"
      badge="ビュー整理済み"
    >
      <OverviewDashboard />
    </AppShell>
  );
}
