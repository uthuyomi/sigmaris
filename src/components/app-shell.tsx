"use client";

import { AuthControls } from "@/components/auth-controls";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { PropsWithChildren, ReactNode } from "react";

const navItems = [
  { href: "/app", label: "ホーム" },
  { href: "/chat", label: "チャット" },
  { href: "/timeline", label: "タイムライン" },
  { href: "/calendar", label: "カレンダー" },
  { href: "/settings", label: "設定" },
];

type AppShellProps = PropsWithChildren<{
  title: string;
  description: string;
  badge?: string;
  actions?: ReactNode;
}>;

export function AppShell({
  title,
  description,
  badge,
  actions,
  children,
}: AppShellProps) {
  const pathname = usePathname();

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(244,162,97,0.22),_transparent_28%),linear-gradient(180deg,_#f8f5ee_0%,_#efe6d3_52%,_#e7dcc5_100%)] text-stone-900">
      <div className="mx-auto flex min-h-screen w-full max-w-[1500px] flex-col px-4 pb-24 pt-4 sm:px-6 lg:px-8">
        <header className="mb-4 rounded-[28px] border border-stone-900/10 bg-white/70 px-4 py-4 shadow-[0_20px_60px_-40px_rgba(41,37,36,0.55)] backdrop-blur">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.3em] text-stone-500">
                ShiftPilotAI
              </p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight">{title}</h1>
              <p className="mt-2 max-w-2xl text-sm leading-7 text-stone-600">
                {description}
              </p>
            </div>

            <div className="flex flex-col items-start gap-3 xl:items-end">
              <div className="flex flex-wrap items-center gap-3">
                {actions}
                {badge ? (
                  <div className="rounded-full bg-stone-900 px-4 py-2 text-sm font-medium text-stone-50">
                    {badge}
                  </div>
                ) : null}
              </div>
              <AuthControls redirectPath={pathname} />
            </div>
          </div>

          <nav className="mt-4 hidden flex-wrap gap-2 lg:flex">
            {navItems.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "rounded-full px-4 py-2 text-sm font-medium transition",
                    active
                      ? "bg-stone-900 text-stone-50"
                      : "bg-stone-900/5 text-stone-700 hover:bg-stone-900/10",
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </header>

        <section className="flex-1">{children}</section>

        <nav className="fixed bottom-4 left-1/2 z-20 flex w-[min(94vw,34rem)] -translate-x-1/2 items-center justify-between rounded-full border border-stone-900/10 bg-white/90 px-4 py-3 shadow-[0_25px_70px_-35px_rgba(28,25,23,0.7)] backdrop-blur lg:hidden">
          {navItems.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-full px-3 py-2 text-sm font-medium",
                  active ? "bg-stone-900 text-stone-50" : "text-stone-600",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </main>
  );
}
