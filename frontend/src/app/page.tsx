import { redirect } from "next/navigation";
import { AuthControls } from "@/components/auth-controls";
import { defaultLocale } from "@/lib/i18n";
import { getCurrentUser } from "@/lib/supabase/auth";

export default async function HomePage() {
  const user = await getCurrentUser();

  if (user) {
    redirect("/app");
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#212121] px-6 py-10 text-[#ececec]">
      <section className="flex w-full max-w-sm flex-col items-center text-center">
        <div className="flex size-24 items-center justify-center rounded-[2rem] bg-[#9b59b6] text-5xl font-semibold text-white shadow-[0_24px_80px_-36px_rgba(155,89,182,0.95)]">
          Σ
        </div>
        <h1 className="mt-8 text-4xl font-semibold tracking-normal text-white">
          シグマリス
        </h1>
        <p className="mt-3 text-sm font-medium text-[#8e8ea0]">
          あなたの家庭支援AI
        </p>

        <div className="mt-10 w-full">
          <AuthControls
            redirectPath="/app"
            locale={defaultLocale}
            mode="sigmaris"
          />
        </div>
      </section>
    </main>
  );
}
