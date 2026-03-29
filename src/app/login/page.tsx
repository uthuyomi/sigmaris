import { FileSpreadsheetIcon, Globe2Icon, ImageIcon } from "lucide-react";
import { redirect } from "next/navigation";
import { AuthControls } from "@/components/auth-controls";
import { defaultLocale, getDictionary } from "@/lib/i18n";
import { getCurrentUser } from "@/lib/supabase/auth";

type LoginPageProps = {
  searchParams?: Promise<{
    next?: string;
  }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const user = await getCurrentUser();
  const params = searchParams ? await searchParams : undefined;
  const next = params?.next && params.next.startsWith("/") ? params.next : "/app";
  const locale = defaultLocale;
  const dict = getDictionary(locale);

  if (user) {
    redirect(next);
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(244,162,97,0.24),_transparent_32%),linear-gradient(180deg,_#f8f5ee_0%,_#efe6d3_52%,_#e7dcc5_100%)] text-stone-900">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-4 py-8 sm:px-6 lg:px-8">
        <section className="grid gap-6 lg:grid-cols-[1fr_380px]">
          <div className="rounded-[36px] border border-stone-900/10 bg-white/75 p-7 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur sm:p-9">
            <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Login</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-tight">{dict.auth.signIn}</h1>
            <p className="mt-5 max-w-2xl text-sm leading-8 text-stone-600 sm:text-base">
              Google Calendar、Sheets、Maps とつないで、そのまま既存の予定操作へ入る。
            </p>

            <div className="mt-8">
              <AuthControls redirectPath={next} locale={locale} mode="hero" />
            </div>
          </div>

          <aside className="rounded-[36px] border border-stone-900/10 bg-stone-900 p-7 text-stone-50 shadow-[0_30px_90px_-50px_rgba(28,25,23,0.9)] sm:p-9">
            <p className="text-xs uppercase tracking-[0.3em] text-stone-400">Ready</p>
            <div className="mt-4 space-y-3">
              {[
                { icon: Globe2Icon, label: "Google" },
                { icon: FileSpreadsheetIcon, label: "Sheets" },
                { icon: ImageIcon, label: "Image import" },
              ].map((item) => (
                <div
                  key={item.label}
                  className="flex items-center gap-3 rounded-[22px] border border-white/10 px-4 py-3"
                >
                  <item.icon className="size-4 text-stone-300" />
                  <span className="text-sm text-stone-200">{item.label}</span>
                </div>
              ))}
            </div>
          </aside>
        </section>
      </div>
    </main>
  );
}
