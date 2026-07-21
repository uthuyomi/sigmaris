"use client";

import type { UIMessage } from "ai";
import {
  ActivityIcon,
  MenuIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Assistant } from "@/app/assistant";
import { SigmarisSidebar } from "@/components/sigmaris-sidebar";
import { LiveSidebarPanel } from "@/components/live/live-sidebar-panel";
import { useLiveEvents } from "@/components/live/use-live-events";
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
  // Sigmaris Live 右サイドパネル(デザイン統一 第五段階)。既定は閉。
  const [liveOpen, setLiveOpen] = useState(false);
  // SSE接続の開閉制御(依頼書「閉じている間はSSE接続を確立しない」への対応):
  // 既存の useLiveEvents をそのまま使い、enabled=liveOpen を渡すだけで、閉時は
  // EventSource を一切開かない(use-live-events.ts の enabled オプション)。
  // 呼び出しは ChatWorkspace で1回のみ行い、events/status を(デスクトップ列・
  // モバイルドロワーの)両方の LiveSidebarPanel へ配る(1接続・複数表示、
  // Live-3 の設計を踏襲)。
  const { events: liveEvents, status: liveStatus } = useLiveEvents(undefined, {
    enabled: liveOpen,
  });

  useEffect(() => {
    const media = window.matchMedia("(min-width: 768px)");
    const syncSidebar = () => setSidebarOpen(media.matches);

    syncSidebar();
    media.addEventListener("change", syncSidebar);

    return () => media.removeEventListener("change", syncSidebar);
  }, []);

  useEffect(() => {
    // 左サイドバー・右Liveパネルのいずれかがモバイルでドロワー表示中は、
    // 背面のスクロールを止める。
    if ((!sidebarOpen && !liveOpen) || !window.matchMedia("(max-width: 767px)").matches) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [sidebarOpen, liveOpen]);

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
          {/* Sigmaris Live 開閉トグル(デザイン統一 第五段階)。右寄せの
              アイコンボタンで、既存のダークなヘッダーに自然に馴染ませる。
              Live はあくまで補助情報のため既定は閉。 */}
          <button
            type="button"
            onClick={() => setLiveOpen((open) => !open)}
            className={cn(
              "flex size-10 shrink-0 items-center justify-center rounded-lg text-[#ececec] transition hover:bg-[#2f2f2f] focus:outline-none focus:ring-2 focus:ring-[#9b59b6]/40",
              liveOpen && "bg-[#2f2f2f] text-white",
            )}
            aria-label={liveOpen ? "Sigmaris Liveを閉じる" : "Sigmaris Liveを開く"}
            aria-pressed={liveOpen}
            title="Sigmaris Live"
          >
            <ActivityIcon className="size-5" />
          </button>
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

      {/* 右: Sigmaris Live パネル(デスクトップはインライン列を幅トランジション
          で開閉。左の会話履歴サイドバーと同じ開閉パターンを踏襲)。閉時は
          w-0 だが、SSE の実接続有無は useLiveEvents の enabled=liveOpen が
          制御する(表示幅とは独立)。 */}
      <div
        className={cn(
          "hidden min-h-0 shrink-0 overflow-hidden border-l border-white/10 bg-[#171717] transition-[width] duration-200 ease-out md:block",
          liveOpen ? "w-[400px]" : "w-0",
        )}
        aria-hidden={!liveOpen}
      >
        <div className="h-full w-[400px]">
          <LiveSidebarPanel
            events={liveEvents}
            status={liveStatus}
            onClose={() => setLiveOpen(false)}
          />
        </div>
      </div>

      {/* 右: モバイルはドロワーオーバーレイ(右からスライドイン、既存の
          swipe-in-from-right キーフレームを再利用)。 */}
      {liveOpen ? (
        <div
          className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[1px] md:hidden"
          onClick={() => setLiveOpen(false)}
        >
          <div
            className="ml-auto h-[100dvh] w-[min(90vw,400px)] animate-[swipe-in-from-right_200ms_ease-out] overflow-hidden bg-[#171717] pb-[env(safe-area-inset-bottom)] shadow-[-24px_0_80px_-48px_rgba(0,0,0,0.95)]"
            onClick={(event) => event.stopPropagation()}
          >
            <LiveSidebarPanel
              events={liveEvents}
              status={liveStatus}
              onClose={() => setLiveOpen(false)}
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}
