"use client";
// 役割: チャットスレッド一覧と選択操作を表示するReactクライアントコンポーネント。


import { getDictionary, type AppLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import {
  BrainCircuitIcon,
  Clock3Icon,
  PencilIcon,
  PlusIcon,
  Settings2Icon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTransition, type ReactNode } from "react";

type ChatThread = {
  id: string;
  title: string;
  updated_at: string;
};

type ChatThreadSidebarProps = {
  locale: AppLocale;
  threads: ChatThread[];
  activeThreadId: string;
  onNavigate?: () => void;
};

export function ChatThreadSidebar({
  locale,
  threads,
  activeThreadId,
  onNavigate,
}: ChatThreadSidebarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();
  const dict = getDictionary(locale);
  const memoryLabel = locale === "ja" ? "記憶" : "Memory";

  const createThread = () => {
    startTransition(async () => {
      const res = await fetch("/api/chat/threads", { method: "POST" });
      const data = await res.json();
      if (!res.ok) return;
      router.push(`/chat?thread=${data.thread.id}`);
      onNavigate?.();
      router.refresh();
    });
  };

  const renameThread = (thread: ChatThread) => {
    const nextTitle = window.prompt(dict.chat.renamePrompt, thread.title)?.trim();
    if (!nextTitle || nextTitle === thread.title) return;

    startTransition(async () => {
      const res = await fetch(`/api/chat/threads/${thread.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: nextTitle }),
      });

      if (!res.ok) return;
      router.refresh();
    });
  };

  const deleteThread = (thread: ChatThread) => {
    const confirmed = window.confirm(`${thread.title}\n${dict.chat.deleteConfirm}`);
    if (!confirmed) return;

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

  const openThread = (threadId: string) => {
    router.push(`/chat?thread=${threadId}`);
    onNavigate?.();
  };

  return (
    <aside className="flex h-full min-h-0 flex-col bg-[#f7f7f8] p-3 text-stone-950 dark:bg-[#171717] dark:text-stone-100">
      <div className="flex items-center justify-between gap-3 px-1 py-1">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.24em] text-stone-500 dark:text-stone-400">{dict.chat.threadList}</p>
          <h2 className="mt-1 text-sm font-semibold text-stone-800 dark:text-stone-200">#{threads.length}</h2>
        </div>
        <button
          type="button"
          onClick={createThread}
          disabled={isPending}
          className="inline-flex size-10 items-center justify-center rounded-xl text-stone-700 transition hover:bg-stone-200 disabled:opacity-70 dark:text-stone-300 dark:hover:bg-white/10"
          aria-label={dict.chat.newThread}
        >
          <PlusIcon className="size-5" />
        </button>
      </div>

      <div className="mt-3 min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
        {threads.map((thread) => {
          const active = thread.id === activeThreadId;

          return (
            <div
              key={thread.id}
              className={`group rounded-xl px-2 py-2 transition ${
                active
                  ? "bg-stone-200 text-stone-950 dark:bg-white/12 dark:text-white"
                  : "text-stone-800 hover:bg-stone-200/70 dark:text-stone-200 dark:hover:bg-white/8"
              }`}
            >
              <button
                type="button"
                onClick={() => openThread(thread.id)}
                className="w-full text-left"
                aria-label={thread.title}
              >
                <p className="line-clamp-2 text-sm font-medium">{thread.title}</p>
                <div className="mt-1 inline-flex items-center gap-1 text-xs text-stone-500 dark:text-stone-400">
                  <Clock3Icon className="size-3" />
                  {new Intl.DateTimeFormat(locale, {
                    month: "numeric",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  }).format(new Date(thread.updated_at))}
                </div>
              </button>

              <div className="mt-2 flex items-center gap-1 opacity-100 sm:opacity-0 sm:transition sm:group-hover:opacity-100">
                <button
                  type="button"
                  onClick={() => renameThread(thread)}
                  className="inline-flex size-8 items-center justify-center rounded-lg text-stone-600 transition hover:bg-stone-300/70 hover:text-stone-950 dark:text-stone-400 dark:hover:bg-white/10 dark:hover:text-white"
                  aria-label={dict.chat.renameThread}
                >
                  <PencilIcon className="size-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => deleteThread(thread)}
                  className="inline-flex size-8 items-center justify-center rounded-lg text-stone-600 transition hover:bg-red-100 hover:text-red-700 dark:text-stone-400 dark:hover:bg-red-500/15 dark:hover:text-red-200"
                  aria-label={dict.chat.deleteThread}
                >
                  <Trash2Icon className="size-3.5" />
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 border-t border-stone-900/10 pt-3 dark:border-white/10">
        <SidebarNavLink
          href="/memory"
          label={memoryLabel}
          active={pathname === "/memory" || pathname.startsWith("/memory/")}
          onNavigate={onNavigate}
          icon={<BrainCircuitIcon className="size-4" />}
        />
        <SidebarNavLink
          href="/settings"
          label={dict.nav.settings}
          active={pathname === "/settings" || pathname.startsWith("/settings/")}
          onNavigate={onNavigate}
          icon={<Settings2Icon className="size-4" />}
        />
      </div>
    </aside>
  );
}

function SidebarNavLink({
  href,
  label,
  active,
  icon,
  onNavigate,
}: {
  href: string;
  label: string;
  active: boolean;
  icon: ReactNode;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      prefetch={false}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "mb-1 flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium transition",
        active
          ? "bg-stone-200 text-stone-950 dark:bg-white/12 dark:text-white"
          : "text-stone-700 hover:bg-stone-200/70 hover:text-stone-950 dark:text-stone-300 dark:hover:bg-white/8 dark:hover:text-white",
      )}
    >
      {icon}
      <span className="truncate">{label}</span>
    </Link>
  );
}
