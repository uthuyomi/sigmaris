import { AppShell } from "@/components/app-shell";
import { readShellSettings } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";

export default async function MemoryPage() {
  const user = await requireUser("/memory");
  const { locale, theme } = await readShellSettings(user.id);

  return (
    <AppShell
      locale={locale}
      title={locale === "ja" ? "記憶" : "Memory"}
      description={
        locale === "ja"
          ? "シグマリスが覚えている事実と自己モデル"
          : "Facts and self-model remembered by Sigmaris"
      }
      badge={locale === "ja" ? "準備中" : "Soon"}
      theme={theme}
    >
      <section className="mx-auto flex min-h-[55dvh] w-full max-w-3xl items-center justify-center px-4 py-10">
        <div className="w-full rounded-2xl border border-stone-900/10 bg-white px-5 py-6 text-stone-900 shadow-[0_18px_60px_-44px_rgba(28,25,23,0.35)] dark:border-white/10 dark:bg-[#2f2f2f] dark:text-stone-100">
          <h2 className="text-base font-semibold">
            {locale === "ja" ? "記憶ページ" : "Memory"}
          </h2>
          <p className="mt-2 text-sm leading-7 text-stone-600 dark:text-stone-300">
            {locale === "ja"
              ? "事実記憶と自己モデルの表示は次のステップで接続します。"
              : "Fact memory and self-model views will be connected in the next step."}
          </p>
        </div>
      </section>
    </AppShell>
  );
}
