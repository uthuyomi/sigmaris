"use client";

import type { UIMessage } from "ai";
import {
  MenuIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Assistant } from "@/app/assistant";
import { SigmarisSidebar } from "@/components/sigmaris-sidebar";
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
}: ChatWorkspaceProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 768px)");
    const syncSidebar = () => setSidebarOpen(media.matches);

    syncSidebar();
    media.addEventListener("change", syncSidebar);

    return () => media.removeEventListener("change", syncSidebar);
  }, []);

  useEffect(() => {
    if (!sidebarOpen || !window.matchMedia("(max-width: 767px)").matches) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [sidebarOpen]);

  // /chat 保護(デザイン統一 第二段階): ルート要素に .dark を明示付与し、この
  // サブツリー全体を常にダークトークン文脈へ固定する(依頼書が推奨した方式)。
  // これにより、light テーマ時や画面遷移直後の一瞬でも、チャット本文・
  // サイドバー・コードブロック等のトークン利用要素がダークのまま描画される
  // (SSR/初回描画から有効)。<body> 直下へ出るポータル(ツールチップ)は
  // このサブツリー外に出るため、chat/page.tsx で AppShell へ theme="dark" を
  // 渡し <html>.dark を維持することで別途カバーしている。見た目は現行のダーク
  // のまま不変。
  return (
    <section className="dark relative flex h-full min-h-0 touch-pan-y overflow-hidden overscroll-x-none bg-[#212121] text-[#ececec]">
      <div
        className={cn(
          "hidden min-h-0 shrink-0 overflow-hidden bg-[#171717] transition-[width] duration-200 ease-out md:block",
          sidebarOpen ? "w-[260px]" : "w-0",
        )}
        aria-hidden={!sidebarOpen}
      >
        <SigmarisSidebar
          threads={threads}
          activeThreadId={activeThreadId}
          onNavigate={() => undefined}
        />
      </div>

      {sidebarOpen ? (
        <div
          className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[1px] md:hidden"
          onClick={() => setSidebarOpen(false)}
        >
          <div
            className="h-[100dvh] w-[min(86vw,320px)] animate-[sigmaris-drawer-in_160ms_ease-out] overflow-hidden bg-[#171717] pb-[env(safe-area-inset-bottom)] shadow-[24px_0_80px_-48px_rgba(0,0,0,0.95)]"
            onClick={(event) => event.stopPropagation()}
          >
            <SigmarisSidebar
              threads={threads}
              activeThreadId={activeThreadId}
              onNavigate={() => setSidebarOpen(false)}
            />
          </div>
        </div>
      ) : null}

      <section className="flex min-w-0 flex-1 flex-col bg-[#212121]">
        <div className="flex min-h-12 shrink-0 items-center gap-2 border-b border-white/0 bg-[#212121]/95 px-2 text-[#ececec] backdrop-blur sm:min-h-14 sm:gap-3 sm:px-4">
          <button
            type="button"
            onClick={() => setSidebarOpen((open) => !open)}
            className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg text-[#ececec] transition hover:bg-[#2f2f2f] focus:outline-none focus:ring-2 focus:ring-[#9b59b6]/40"
            aria-label={sidebarOpen ? "サイドバーを閉じる" : "サイドバーを開く"}
            aria-pressed={sidebarOpen}
          >
            {sidebarOpen ? (
              <>
                <XIcon className="size-5 md:hidden" />
                <PanelLeftCloseIcon className="hidden size-5 md:block" />
              </>
            ) : (
              <>
                <MenuIcon className="size-5 md:hidden" />
                <PanelLeftOpenIcon className="hidden size-5 md:block" />
              </>
            )}
          </button>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-semibold sm:text-base">
              {activeThreadTitle || "シグマリス"}
            </h2>
          </div>
        </div>

        <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
          <Assistant
            key={activeThreadId}
            threadId={activeThreadId}
            initialMessages={initialMessages}
            locale={locale}
          />
        </div>
      </section>
    </section>
  );
}
