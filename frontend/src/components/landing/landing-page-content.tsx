import {
  ArrowRightIcon,
  CalendarCheck2Icon,
  CalendarDaysIcon,
  CheckCircle2Icon,
  Clock3Icon,
  FileSpreadsheetIcon,
  ImageIcon,
  MapPinnedIcon,
  MessageSquareMoreIcon,
  RouteIcon,
  SparklesIcon,
} from "lucide-react";
import Link from "next/link";
import { PwaInstallPanel } from "@/components/pwa-install-panel";
import type { LandingCopy, LandingUseCaseIcon } from "@/i18n/landing";

const landingUseCaseIcons = {
  image: ImageIcon,
  sheets: FileSpreadsheetIcon,
  route: RouteIcon,
  calendar: CalendarCheck2Icon,
} satisfies Record<LandingUseCaseIcon, typeof ImageIcon>;

type LandingPageContentProps = {
  copy: LandingCopy;
};

export function LandingPageContent({ copy }: LandingPageContentProps) {
  return (
    <main className="min-h-screen bg-[#f7f2e8] text-stone-900">
      <section className="relative min-h-[86dvh] overflow-hidden border-b border-stone-900/10 bg-[#efe3cf]">
        <div className="absolute inset-0">
          <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(239,227,207,0.96)_0%,rgba(239,227,207,0.82)_40%,rgba(239,227,207,0.38)_100%)]" />
          <div className="absolute right-[-3rem] top-20 hidden w-[52rem] rotate-[-4deg] rounded-[34px] border border-stone-900/10 bg-white/78 p-5 shadow-[0_45px_120px_-65px_rgba(41,37,36,0.85)] backdrop-blur md:block">
            <div className="flex items-center justify-between border-b border-stone-900/10 pb-4">
              <div>
                <p className="text-xs uppercase tracking-[0.26em] text-stone-500">
                  {copy.previewEyebrow}
                </p>
                <h2 className="mt-1 text-xl font-semibold">
                  {copy.previewTitle}
                </h2>
              </div>
              <CalendarDaysIcon className="size-6 text-stone-500" />
            </div>
            <div className="mt-5 grid gap-3">
              {copy.previewItems.map(([time, title, detail]) => (
                <div
                  key={`${time}-${title}`}
                  className="grid grid-cols-[5rem_1fr] gap-4 rounded-[22px] border border-stone-900/10 bg-stone-50/90 px-4 py-4"
                >
                  <span className="text-sm font-semibold text-[#d95f42]">
                    {time}
                  </span>
                  <span>
                    <span className="block text-sm font-semibold text-stone-900">
                      {title}
                    </span>
                    <span className="mt-1 block text-xs leading-6 text-stone-600">
                      {detail}
                    </span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="relative z-10 mx-auto flex min-h-[86dvh] max-w-6xl flex-col px-4 py-5 sm:px-6 lg:px-8">
          <header className="flex items-center justify-between">
            <Link href="/" className="inline-flex items-center gap-3">
              <span className="inline-flex size-10 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
                <SparklesIcon className="size-5" />
              </span>
              <span>
                <span className="block text-sm font-semibold">
                  ShiftPilotAI
                </span>
                <span className="block text-xs text-stone-600">
                  {copy.tagline}
                </span>
              </span>
            </Link>

            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-full bg-stone-900 px-4 py-2 text-sm font-semibold text-stone-50"
            >
              {copy.login}
              <ArrowRightIcon className="size-4" />
            </Link>
          </header>

          <div className="flex flex-1 items-center py-12">
            <div className="max-w-3xl">
              <p className="text-xs font-medium uppercase tracking-[0.28em] text-stone-600">
                {copy.heroEyebrow}
              </p>
              <h1 className="mt-4 text-4xl font-semibold leading-tight tracking-tight sm:text-5xl lg:text-6xl">
                {copy.heroTitle}
              </h1>
              <p className="mt-5 max-w-2xl text-base leading-8 text-stone-700">
                {copy.heroBody}
              </p>

              <div className="mt-7 grid max-w-2xl gap-3 sm:grid-cols-3">
                {copy.heroCards.map(([label, detail]) => (
                  <div
                    key={label}
                    className="rounded-[20px] border border-stone-900/10 bg-white/76 px-4 py-3 backdrop-blur"
                  >
                    <p className="text-sm font-semibold">{label}</p>
                    <p className="mt-1 text-xs leading-6 text-stone-600">
                      {detail}
                    </p>
                  </div>
                ))}
              </div>

              <div className="mt-8 flex flex-wrap items-center gap-3">
                <Link
                  href="/login"
                  className="inline-flex items-center gap-2 rounded-full bg-stone-900 px-6 py-3 text-sm font-semibold text-stone-50"
                >
                  {copy.primaryCta}
                  <ArrowRightIcon className="size-4" />
                </Link>
                <a
                  href="#details"
                  className="rounded-full border border-stone-900/15 bg-white/75 px-6 py-3 text-sm font-semibold text-stone-800"
                >
                  {copy.secondaryCta}
                </a>
              </div>

              <PwaInstallPanel />
            </div>
          </div>
        </div>
      </section>

      <section
        id="details"
        className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:px-8"
      >
        <div className="max-w-3xl">
          <p className="text-xs font-medium uppercase tracking-[0.28em] text-stone-500">
            {copy.detailsEyebrow}
          </p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight">
            {copy.detailsTitle}
          </h2>
          <p className="mt-3 text-sm leading-7 text-stone-600">
            {copy.detailsBody}
          </p>
        </div>

        <div className="mt-7 grid gap-4 md:grid-cols-2">
          {copy.useCases.map((item) => {
            const Icon = landingUseCaseIcons[item.icon];

            return (
              <article
                key={item.title}
                className="rounded-[26px] border border-stone-900/10 bg-white p-5 shadow-[0_26px_70px_-55px_rgba(41,37,36,0.65)]"
              >
                <div className="inline-flex size-11 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
                  <Icon className="size-5" />
                </div>
                <h3 className="mt-4 text-lg font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-7 text-stone-600">
                  {item.text}
                </p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="bg-white">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-12 sm:px-6 lg:grid-cols-[0.9fr_1.1fr] lg:px-8">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.28em] text-stone-500">
              {copy.workflowEyebrow}
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight">
              {copy.workflowTitle}
            </h2>
            <p className="mt-3 text-sm leading-7 text-stone-600">
              {copy.workflowBody}
            </p>
          </div>

          <div className="grid gap-3">
            {copy.workflow.map((item) => (
              <div
                key={item.step}
                className="grid grid-cols-[3rem_1fr] gap-4 rounded-[24px] border border-stone-900/10 bg-[#f7f2e8] px-4 py-4"
              >
                <span className="inline-flex size-10 items-center justify-center rounded-full bg-stone-900 text-sm font-semibold text-stone-50">
                  {item.step}
                </span>
                <span>
                  <span className="block text-base font-semibold">
                    {item.title}
                  </span>
                  <span className="mt-1 block text-sm leading-7 text-stone-600">
                    {item.text}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="grid gap-5 lg:grid-cols-[1fr_0.9fr]">
          <div className="rounded-[30px] border border-stone-900/10 bg-[#274c4a] p-6 text-stone-50">
            <p className="text-xs uppercase tracking-[0.28em] text-stone-300">
              {copy.examplesEyebrow}
            </p>
            <h2 className="mt-3 text-2xl font-semibold">
              {copy.examplesTitle}
            </h2>
            <div className="mt-5 space-y-3">
              {copy.examples.map((example) => (
                <div
                  key={example}
                  className="rounded-[22px] border border-white/10 bg-white/8 px-4 py-4 text-sm leading-7 text-stone-100"
                >
                  「{example}」
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[30px] border border-stone-900/10 bg-white p-6">
            <div className="flex items-start gap-3">
              <CheckCircle2Icon className="mt-1 size-5 text-[#2a9d8f]" />
              <div>
                <h2 className="text-xl font-semibold">{copy.audienceTitle}</h2>
                <ul className="mt-4 space-y-3 text-sm leading-7 text-stone-600">
                  {copy.audienceItems.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap gap-2">
              {[
                { icon: MessageSquareMoreIcon, label: "Chat" },
                { icon: CalendarDaysIcon, label: "Calendar" },
                { icon: MapPinnedIcon, label: "Maps" },
                { icon: Clock3Icon, label: "Timeline" },
              ].map((item) => (
                <span
                  key={item.label}
                  className="inline-flex items-center gap-2 rounded-full border border-stone-900/10 bg-stone-50 px-3 py-2 text-xs font-medium text-stone-700"
                >
                  <item.icon className="size-3.5" />
                  {item.label}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
