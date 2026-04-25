"use client";
// 役割: アプリ全体のナビゲーションと共通レイアウトを構成するReactコンポーネント。


import { AuthControls } from "@/components/auth-controls";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { getDictionary, type AppLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import {
  CalendarDaysIcon,
  MessageSquareMoreIcon,
  Settings2Icon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { PropsWithChildren, ReactNode } from "react";

type AppShellProps = PropsWithChildren<{
  locale: AppLocale;
  title: string;
  description: string;
  badge?: string;
  actions?: ReactNode;
  fitViewport?: boolean;
}>;

const navIconByPath = {
  "/chat": MessageSquareMoreIcon,
  "/calendar": CalendarDaysIcon,
  "/settings": Settings2Icon,
} as const;

export function AppShell({
  locale,
  title,
  description,
  badge,
  actions,
  fitViewport = false,
  children,
}: AppShellProps) {
  const pathname = usePathname();
  const dict = getDictionary(locale);
  const navItems = [
    { href: "/chat", label: dict.nav.chat },
    { href: "/calendar", label: dict.nav.calendar },
    { href: "/settings", label: dict.nav.settings },
  ];

  return (
    <main
      className={cn(
        "min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(244,162,97,0.22),_transparent_28%),linear-gradient(180deg,_#f8f5ee_0%,_#efe6d3_52%,_#e7dcc5_100%)] text-stone-900",
        fitViewport && "h-[100dvh] overflow-hidden",
      )}
    >
      <div
        className={cn(
          "mx-auto flex min-h-screen w-full max-w-[1500px] flex-col px-4 pb-24 pt-4 sm:px-6 lg:px-8 lg:pb-8",
          fitViewport && "h-full min-h-0 overflow-hidden pb-4",
        )}
      >
        <header className="mb-4 rounded-[30px] border border-stone-900/10 bg-white/78 px-4 py-4 shadow-[0_20px_60px_-40px_rgba(41,37,36,0.55)] backdrop-blur">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex items-start gap-4">
              <div className="hidden size-14 items-center justify-center rounded-[22px] bg-stone-900 text-stone-50 sm:inline-flex">
                <CalendarDaysIcon className="size-6" />
              </div>
              <div>
                <p className="text-[11px] font-medium uppercase tracking-[0.32em] text-stone-500">
                  {dict.common.appName}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
                  {badge ? (
                    <span className="rounded-full bg-stone-900 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-stone-50">
                      {badge}
                    </span>
                  ) : null}
                </div>
                <p className="mt-2 text-sm leading-7 text-stone-600">{description}</p>
              </div>
            </div>

            <div className="flex flex-col items-start gap-3 xl:items-end">
              <div className="flex flex-wrap items-center gap-3">
                {actions}
                <nav className="hidden items-center gap-2 lg:flex">
                  {navItems.map((item) => {
                    const active = pathname === item.href;
                    const Icon = navIconByPath[item.href as keyof typeof navIconByPath];

                    return (
                      <Tooltip key={item.href}>
                        <TooltipTrigger>
                          <Link
                            href={item.href}
                            aria-label={item.label}
                            className={cn(
                              "inline-flex size-12 items-center justify-center rounded-2xl border transition",
                              active
                                ? "border-stone-900 bg-stone-900 text-stone-50"
                                : "border-stone-900/10 bg-stone-50 text-stone-600 hover:bg-white",
                            )}
                          >
                            <Icon className="size-5" />
                          </Link>
                        </TooltipTrigger>
                        <TooltipContent>{item.label}</TooltipContent>
                      </Tooltip>
                    );
                  })}
                </nav>
              </div>
              <AuthControls redirectPath={pathname} locale={locale} />
            </div>
          </div>
        </header>

        <section className={cn("flex-1 min-h-0", fitViewport && "overflow-hidden")}>
          {children}
        </section>

        <nav className="fixed bottom-4 left-1/2 z-20 flex w-[min(94vw,20rem)] -translate-x-1/2 items-center justify-between rounded-full border border-stone-900/10 bg-white/92 px-4 py-3 shadow-[0_25px_70px_-35px_rgba(28,25,23,0.7)] backdrop-blur lg:hidden">
          {navItems.map((item) => {
            const active = pathname === item.href;
            const Icon = navIconByPath[item.href as keyof typeof navIconByPath];
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-label={item.label}
                className={cn(
                  "relative inline-flex size-11 items-center justify-center rounded-full transition",
                  active ? "bg-stone-900 text-stone-50" : "text-stone-600",
                )}
              >
                <Icon className="size-5" />
                <span className="sr-only">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </main>
  );
}
