import { AppShell } from "@/components/app-shell";
import { SigmarisChat } from "@/components/sigmaris-chat";
import { readShellSettings } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";

export default async function SigmarisPage() {
  const user = await requireUser("/sigmaris");
  const { locale, theme } = await readShellSettings(user.id);

  return (
    <AppShell
      locale={locale}
      title="Sigmaris"
      description="予定を整理し、必要なエージェントへつなぐ統括インターフェース"
      badge="Orchestrator"
      theme={theme}
      fitViewport
    >
      <SigmarisChat />
    </AppShell>
  );
}
