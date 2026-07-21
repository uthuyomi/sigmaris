"use client";

import { cn } from "@/lib/utils";
import {
  ActivityIcon,
  BrainCircuitIcon,
  MoreHorizontalIcon,
  PencilIcon,
  Settings2Icon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

type ChatThread = {
  id: string;
  title: string;
  updated_at: string;
};

type ThreadGroup = {
  label: string;
  threads: ChatThread[];
};

type SigmarisSidebarProps = {
  threads: ChatThread[];
  activeThreadId: string;
  onNavigate?: () => void;
};

const startOfDay = (date: Date) =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate());

const groupThreads = (threads: ChatThread[]): ThreadGroup[] => {
  const now = startOfDay(new Date());
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const pastSeven = new Date(now);
  pastSeven.setDate(now.getDate() - 7);

  const groups: ThreadGroup[] = [
    { label: "今日", threads: [] },
    { label: "昨日", threads: [] },
    { label: "過去7日間", threads: [] },
    { label: "以前", threads: [] },
  ];

  for (const thread of threads) {
    const updatedAt = startOfDay(new Date(thread.updated_at));
    if (updatedAt >= now) {
      groups[0].threads.push(thread);
    } else if (updatedAt >= yesterday) {
      groups[1].threads.push(thread);
    } else if (updatedAt >= pastSeven) {
      groups[2].threads.push(thread);
    } else {
      groups[3].threads.push(thread);
    }
  }

  return groups.filter((group) => group.threads.length > 0);
};

export function SigmarisSidebar({
  threads,
  activeThreadId,
  onNavigate,
}: SigmarisSidebarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();
  const [openMenuThreadId, setOpenMenuThreadId] = useState<string | null>(null);
  const groups = useMemo(() => groupThreads(threads), [threads]);

  const createThread = () => {
    startTransition(async () => {
      const threadId = crypto.randomUUID();
      const res = await fetch("/api/chat/threads", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ threadId }),
      });
      const data = await res.json();
      if (!res.ok) return;

      router.push(`/chat?thread=${data.thread?.id ?? threadId}`);
      onNavigate?.();
      router.refresh();
    });
  };

  const openThread = (threadId: string) => {
    setOpenMenuThreadId(null);
    router.push(`/chat?thread=${threadId}`);
    onNavigate?.();
  };

  const deleteThread = (thread: ChatThread) => {
    startTransition(async () => {
      const res = await fetch(`/api/chat/threads/${thread.id}`, {
        method: "DELETE",
      });

      if (!res.ok) return;

      if (thread.id === activeThreadId) {
        router.push("/chat");
      }
      router.refresh();
    });
  };

  return (
    <aside className="flex h-full min-h-0 w-[260px] max-w-full flex-col bg-[#171717] text-[#ececec]">
      <div className="flex h-14 shrink-0 items-center justify-between px-3 pt-[env(safe-area-inset-top)]">
        <Link
          href="/chat"
          onClick={onNavigate}
          className="flex min-w-0 items-center gap-2 rounded-lg px-2 py-2 text-sm font-semibold transition hover:bg-[#2f2f2f]"
        >
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-[#9b59b6] text-base font-semibold text-white">
            Σ
          </span>
          <span className="truncate">シグマリス</span>
        </Link>
        <button
          type="button"
          onClick={createThread}
          disabled={isPending}
          className="flex size-9 shrink-0 items-center justify-center rounded-lg text-[#ececec] transition hover:bg-[#2f2f2f] disabled:opacity-50"
          aria-label="新しいチャット"
          title="新しいチャット"
        >
          <PencilIcon className="size-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3 overscroll-contain">
        {groups.length ? (
          groups.map((group) => (
            <section key={group.label} className="pt-3">
              <h2 className="px-2 pb-1.5 text-xs font-medium text-[#8e8ea0]">
                {group.label}
              </h2>
              <div className="space-y-0.5">
                {group.threads.map((thread) => {
                  const active = thread.id === activeThreadId;

                  return (
                    <div
                      key={thread.id}
                      onContextMenu={(event) => {
                        event.preventDefault();
                        deleteThread(thread);
                      }}
                      className={cn(
                        "group/thread relative flex min-h-9 items-center rounded-lg text-sm transition",
                        active ? "bg-[#2f2f2f]" : "hover:bg-[#2f2f2f]",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => openThread(thread.id)}
                        className="min-w-0 flex-1 truncate px-2 py-2 pr-9 text-left"
                        aria-current={active ? "page" : undefined}
                        aria-label={thread.title}
                      >
                        {thread.title}
                      </button>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenMenuThreadId((current) =>
                            current === thread.id ? null : thread.id,
                          );
                        }}
                        disabled={isPending}
                        className="absolute right-1 top-1/2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-[#8e8ea0] opacity-100 transition hover:bg-white/10 hover:text-[#ececec] disabled:opacity-40 md:opacity-0 md:group-hover/thread:opacity-100"
                        aria-label={`${thread.title}のメニュー`}
                        aria-expanded={openMenuThreadId === thread.id}
                        title="メニュー"
                      >
                        <MoreHorizontalIcon className="size-4" />
                        <span className="sr-only">メニュー</span>
                      </button>
                      {openMenuThreadId === thread.id ? (
                        <div className="absolute right-1 top-9 z-20 w-32 rounded-xl border border-white/10 bg-[#2f2f2f] p-1 shadow-[0_18px_45px_-24px_rgba(0,0,0,0.9)]">
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              setOpenMenuThreadId(null);
                              deleteThread(thread);
                            }}
                            className="flex min-h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-sm text-red-300 transition hover:bg-white/10"
                          >
                            <Trash2Icon className="size-4" />
                            削除
                          </button>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </section>
          ))
        ) : (
          <p className="px-2 py-4 text-sm text-[#8e8ea0]">
            チャット履歴はまだありません
          </p>
        )}
      </div>

      <div className="shrink-0 border-t border-white/10 p-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))]">
        {/* デザイン統一(ナビ一本化): /chat からも主要ページへ行けるよう、
            SigmarisSidebar 既存のダークな SidebarLink 様式で追加している。
            第四段階(記憶ページ統合)で /timeline は /memory の「変遷」タブへ
            統合されたため、独立したタイムラインリンクは廃止し「記憶」に集約
            した。並び順・アイコンは AppShell の navItems/navIconByPath と揃える
            (chat→memory→growth→settings、growth=Activity)。 */}
        <SidebarLink
          href="/memory"
          label="記憶"
          active={pathname === "/memory" || pathname.startsWith("/memory/")}
          icon={<BrainCircuitIcon className="size-4" />}
          onNavigate={onNavigate}
        />
        <SidebarLink
          href="/growth"
          label="成長ログ"
          active={pathname === "/growth" || pathname.startsWith("/growth/")}
          icon={<ActivityIcon className="size-4" />}
          onNavigate={onNavigate}
        />
        <SidebarLink
          href="/settings"
          label="設定"
          active={pathname === "/settings" || pathname.startsWith("/settings/")}
          icon={<Settings2Icon className="size-4" />}
          onNavigate={onNavigate}
        />
      </div>
    </aside>
  );
}

function SidebarLink({
  href,
  label,
  active,
  icon,
  onNavigate,
}: {
  href: string;
  label: string;
  active: boolean;
  icon: React.ReactNode;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className={cn(
        "flex min-h-10 items-center gap-2 rounded-lg px-2 text-sm transition",
        active ? "bg-[#2f2f2f] text-[#ececec]" : "text-[#ececec] hover:bg-[#2f2f2f]",
      )}
    >
      {icon}
      <span className="truncate">{label}</span>
    </Link>
  );
}
