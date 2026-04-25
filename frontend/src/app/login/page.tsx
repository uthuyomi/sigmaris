// 役割: ログイン画面を表示するNext.jsページ。
import {
  CalendarClockIcon,
  CheckCircle2Icon,
  FileSpreadsheetIcon,
  ImageIcon,
  MapPinnedIcon,
  ShieldCheckIcon,
} from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AuthControls } from "@/components/auth-controls";
import { defaultLocale } from "@/lib/i18n";
import { getCurrentUser } from "@/lib/supabase/auth";

type LoginPageProps = {
  searchParams?: Promise<{
    next?: string;
  }>;
};

const connectedTools = [
  {
    icon: CalendarClockIcon,
    title: "Google Calendar",
    text: "確認した予定や移動予定を保存します。",
  },
  {
    icon: FileSpreadsheetIcon,
    title: "Google Sheets",
    text: "勤務表や予定表のURLを読み取ります。",
  },
  {
    icon: MapPinnedIcon,
    title: "Google Maps",
    text: "移動時間や出発時刻の目安を出します。",
  },
  {
    icon: ImageIcon,
    title: "画像取り込み",
    text: "スクリーンショットから予定候補を作ります。",
  },
];

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const user = await getCurrentUser();
  const params = searchParams ? await searchParams : undefined;
  const next = params?.next && params.next.startsWith("/") ? params.next : "/app";
  const locale = defaultLocale;

  if (user) {
    redirect(next);
  }

  return (
    <main className="min-h-screen bg-[#f6f1e7] text-stone-900">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-4 py-5 sm:px-6 lg:px-8">
        <header className="flex items-center justify-between">
          <Link href="/" className="text-sm font-semibold text-stone-700">
            ShiftPilotAI
          </Link>
          <Link
            href="/"
            className="rounded-full border border-stone-900/10 bg-white px-4 py-2 text-sm font-medium text-stone-700"
          >
            トップへ
          </Link>
        </header>

        <section className="grid flex-1 items-center gap-6 py-10 lg:grid-cols-[0.95fr_1.05fr]">
          <div className="rounded-[34px] border border-stone-900/10 bg-white p-7 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] sm:p-9">
            <div className="inline-flex items-center gap-2 rounded-full border border-stone-900/10 bg-stone-50 px-3 py-2 text-xs font-medium text-stone-600">
              <ShieldCheckIcon className="size-4" />
              Google連携で始めます
            </div>
            <h1 className="mt-5 text-4xl font-semibold leading-tight tracking-tight">
              予定の取り込みと保存に必要な連携を行います。
            </h1>
            <p className="mt-4 text-sm leading-7 text-stone-600 sm:text-base">
              ログインすると、Google Calendarへの保存、Sheets URLの読み取り、予定に合わせた移動時間の確認が使えるようになります。予定候補は確認してから保存できます。
            </p>

            <div className="mt-7">
              <AuthControls redirectPath={next} locale={locale} mode="hero" />
            </div>

            <p className="mt-5 text-xs leading-6 text-stone-500">
              Google CalendarとSheetsの権限は、予定の読み取り・保存・取り込みに使います。
            </p>
          </div>

          <aside className="space-y-4">
            <section className="rounded-[34px] border border-stone-900/10 bg-[#274c4a] p-7 text-stone-50 shadow-[0_30px_90px_-50px_rgba(28,25,23,0.86)] sm:p-8">
              <p className="text-xs uppercase tracking-[0.28em] text-stone-300">After login</p>
              <h2 className="mt-3 text-2xl font-semibold">ログイン後に使えること</h2>
              <div className="mt-5 grid gap-3 sm:grid-cols-2">
                {connectedTools.map((item) => (
                  <div
                    key={item.title}
                    className="rounded-[22px] border border-white/10 bg-white/8 px-4 py-4"
                  >
                    <div className="flex items-center gap-3">
                      <item.icon className="size-5 text-[#f4a261]" />
                      <h3 className="text-sm font-semibold">{item.title}</h3>
                    </div>
                    <p className="mt-2 text-xs leading-6 text-stone-300">{item.text}</p>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-[30px] border border-stone-900/10 bg-white p-5">
              <div className="flex items-start gap-3">
                <CheckCircle2Icon className="mt-0.5 size-5 text-[#2a9d8f]" />
                <div>
                  <h2 className="text-base font-semibold">最初の使い方</h2>
                  <p className="mt-2 text-sm leading-7 text-stone-600">
                    まずGoogle Calendarを同期し、そのあと勤務表の画像やSheets URLをチャットに送ります。読み取った予定候補を確認してから保存できます。
                  </p>
                </div>
              </div>
            </section>
          </aside>
        </section>
      </div>
    </main>
  );
}
