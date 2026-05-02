"use client";

import type { UIMessage } from "ai";
import { PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Assistant } from "@/app/assistant";
import { ChatThreadSidebar } from "@/components/chat-thread-sidebar";
import type { AppLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type ChatThread = {
  id: string;
  title: string;
  updated_at: string;
};

type ChatWorkspaceProps = {
  locale: AppLocale;
  threads: ChatThread[];
  activeThreadId: string;
  activeThreadTitle: string;
  initialMessages: UIMessage[];
  assistantLabel: string;
};

export function ChatWorkspace({
  locale,
  threads,
  activeThreadId,
  activeThreadTitle,
  initialMessages,
  assistantLabel,
}: ChatWorkspaceProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 1024px)");
    const syncSidebar = () => setSidebarOpen(media.matches);

    syncSidebar();
    media.addEventListener("change", syncSidebar);

    return () => media.removeEventListener("change", syncSidebar);
  }, []);

  return (
    <section className="relative flex h-full min-h-0 overflow-hidden rounded-2xl border border-stone-900/10 bg-white shadow-[0_18px_60px_-44px_rgba(28,25,23,0.35)] dark:border-white/10 dark:bg-[#212121]">
      <div
        className={cn(
          "hidden min-h-0 shrink-0 overflow-hidden border-r border-stone-900/10 bg-[#f7f7f8] transition-[width] duration-200 ease-out dark:border-white/10 dark:bg-[#171717] lg:block",
          sidebarOpen ? "w-[300px]" : "w-0",
        )}
        aria-hidden={!sidebarOpen}
      >
        <ChatThreadSidebar
          locale={locale}
          threads={threads}
          activeThreadId={activeThreadId}
          onNavigate={() => undefined}
        />
      </div>

      {sidebarOpen ? (
        <div className="absolute inset-0 z-30 bg-stone-950/40 backdrop-blur-[1px] lg:hidden" onClick={() => setSidebarOpen(false)}>
          <div
            className="h-full w-[min(86vw,320px)] border-r border-stone-900/10 bg-[#f7f7f8] shadow-[24px_0_80px_-48px_rgba(28,25,23,0.95)] dark:border-white/10 dark:bg-[#171717]"
            onClick={(event) => event.stopPropagation()}
          >
            <ChatThreadSidebar
              locale={locale}
              threads={threads}
              activeThreadId={activeThreadId}
              onNavigate={() => setSidebarOpen(false)}
            />
          </div>
        </div>
      ) : null}

      <section className="flex min-w-0 flex-1 flex-col bg-white dark:bg-[#212121]">
        <div className="flex min-h-14 items-center gap-3 border-b border-stone-900/10 px-3 text-stone-900 dark:border-white/10 dark:text-stone-100 sm:px-4">
          <button
            type="button"
            onClick={() => setSidebarOpen((open) => !open)}
            className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl text-stone-600 transition hover:bg-stone-100 hover:text-stone-950 focus:outline-none focus:ring-2 focus:ring-stone-900/15 dark:text-stone-300 dark:hover:bg-white/10 dark:hover:text-white"
            aria-label={sidebarOpen ? "Close thread list" : "Open thread list"}
            aria-pressed={sidebarOpen}
          >
            {sidebarOpen ? <PanelLeftCloseIcon className="size-5" /> : <PanelLeftOpenIcon className="size-5" />}
          </button>
          <div className="min-w-0">
            <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-stone-400">
              {assistantLabel}
            </p>
            <h2 className="truncate text-sm font-semibold sm:text-base">{activeThreadTitle}</h2>
          </div>
        </div>

        <div className="min-h-0 flex-1">
          <Assistant threadId={activeThreadId} initialMessages={initialMessages} locale={locale} />
        </div>
      </section>
    </section>
  );
}
