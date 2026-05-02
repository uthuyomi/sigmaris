"use client";
// 役割: アプリ全体のナビゲーションと共通レイアウトを構成するReactコンポーネント。


import { AuthControls } from "@/components/auth-controls";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { getDictionary, type AppLocale } from "@/lib/i18n";
import type { AppTheme } from "@/lib/profile-settings";
import { cn } from "@/lib/utils";
import {
  CalendarDaysIcon,
  MessageSquareMoreIcon,
  Settings2Icon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, type PropsWithChildren, type ReactNode } from "react";

type AppShellProps = PropsWithChildren<{
  locale: AppLocale;
  title: string;
  description: string;
  badge?: string;
  actions?: ReactNode;
  fitViewport?: boolean;
  theme?: AppTheme;
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
  theme = "light",
  children,
}: AppShellProps) {
  const pathname = usePathname();
  const dict = getDictionary(locale);
  const navItems = [
    { href: "/chat", label: dict.nav.chat },
    { href: "/calendar", label: dict.nav.calendar },
    { href: "/settings", label: dict.nav.settings },
  ];
  const activeNavItem = navItems.find((item) => item.href === pathname) ?? navItems[0];
  const ActiveIcon = navIconByPath[activeNavItem.href as keyof typeof navIconByPath];

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <main
      className={cn(
        "min-h-screen bg-[#f7f7f8] text-stone-950 dark:bg-[#212121] dark:text-stone-100",
        theme === "dark" && "dark",
        fitViewport && "h-[100dvh] overflow-hidden",
      )}
    >
      <div
        className={cn(
          "mx-auto flex min-h-screen w-full max-w-[1500px] flex-col px-3 pb-4 pt-3 sm:px-4 lg:px-5",
          fitViewport && "h-full min-h-0 overflow-hidden",
        )}
      >
        <header className="mb-3 rounded-2xl border border-stone-900/10 bg-white px-3 py-3 shadow-[0_14px_45px_-34px_rgba(28,25,23,0.45)] dark:border-white/10 dark:bg-[#2f2f2f] sm:px-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <div className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-stone-950 text-white dark:bg-white dark:text-stone-950">
                <ActiveIcon className="size-5" />
              </div>
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <h1 className="truncate text-base font-semibold tracking-tight sm:text-lg">{title}</h1>
                  {badge ? (
                    <span className="hidden rounded-full border border-stone-900/10 bg-stone-100 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.14em] text-stone-500 dark:border-white/10 dark:bg-white/8 dark:text-stone-400 sm:inline-flex">
                      {badge}
                    </span>
                  ) : null}
                </div>
                <p className="mt-0.5 hidden max-w-[42rem] truncate text-xs text-stone-500 dark:text-stone-400 md:block">{description}</p>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <div className="hidden items-center gap-2 sm:flex">
                {actions}
              </div>
              <nav className="flex items-center gap-1 rounded-xl bg-stone-100 p-1 dark:bg-white/8">
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
                            "inline-flex size-9 items-center justify-center rounded-lg transition sm:size-10",
                            active
                              ? "bg-white text-stone-950 shadow-sm dark:bg-[#424242] dark:text-white"
                              : "text-stone-500 hover:bg-white/75 hover:text-stone-950 dark:text-stone-400 dark:hover:bg-white/10 dark:hover:text-white",
                          )}
                        >
                          <Icon className="size-[18px]" />
                        </Link>
                      </TooltipTrigger>
                      <TooltipContent>{item.label}</TooltipContent>
                    </Tooltip>
                  );
                })}
              </nav>
              <AuthControls redirectPath={pathname} locale={locale} mode="icon" />
            </div>
          </div>
        </header>

        <section className={cn("flex-1 min-h-0", fitViewport && "overflow-hidden")}>
          {children}
        </section>
      </div>
    </main>
  );
}
