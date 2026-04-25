"use client";
// 役割: チャットスレッド一覧と選択操作を表示するReactクライアントコンポーネント。


import { getDictionary, type AppLocale } from "@/lib/i18n";
import { Clock3Icon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

type ChatThread = {
  id: string;
  title: string;
  updated_at: string;
};

type ChatThreadSidebarProps = {
  locale: AppLocale;
  threads: ChatThread[];
  activeThreadId: string;
};

export function ChatThreadSidebar({
  locale,
  threads,
  activeThreadId,
}: ChatThreadSidebarProps) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const dict = getDictionary(locale);

  const createThread = () => {
    startTransition(async () => {
      const res = await fetch("/api/chat/threads", { method: "POST" });
      const data = await res.json();
      if (!res.ok) return;
      router.push(`/chat?thread=${data.thread.id}`);
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

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-[32px] border border-stone-900/10 bg-white/78 p-4 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-stone-500">{dict.chat.threadList}</p>
          <h2 className="mt-2 text-lg font-semibold text-stone-900">#{threads.length}</h2>
        </div>
        <button
          type="button"
          onClick={createThread}
          disabled={isPending}
          className="inline-flex size-11 items-center justify-center rounded-2xl bg-stone-900 text-stone-50 transition hover:bg-stone-800 disabled:opacity-70"
          aria-label={dict.chat.newThread}
        >
          <PlusIcon className="size-4" />
        </button>
      </div>

      <div className="mt-4 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {threads.map((thread) => {
          const active = thread.id === activeThreadId;

          return (
            <div
              key={thread.id}
              className={`rounded-[24px] border p-3 transition ${
                active
                  ? "border-stone-900 bg-stone-900 text-stone-50"
                  : "border-stone-900/10 bg-stone-50 text-stone-900 hover:bg-white"
              }`}
            >
              <button
                type="button"
                onClick={() => router.push(`/chat?thread=${thread.id}`)}
                className="w-full text-left"
                aria-label={thread.title}
              >
                <p className="line-clamp-2 text-sm font-semibold">{thread.title}</p>
                <div className={`mt-2 inline-flex items-center gap-1 text-xs ${active ? "text-stone-300" : "text-stone-500"}`}>
                  <Clock3Icon className="size-3" />
                  {new Intl.DateTimeFormat(locale, {
                    month: "numeric",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  }).format(new Date(thread.updated_at))}
                </div>
              </button>

              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => renameThread(thread)}
                  className={`inline-flex size-9 items-center justify-center rounded-full ${
                    active ? "bg-white/10 text-stone-100" : "bg-stone-900/5 text-stone-700"
                  }`}
                  aria-label={dict.chat.renameThread}
                >
                  <PencilIcon className="size-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => deleteThread(thread)}
                  className={`inline-flex size-9 items-center justify-center rounded-full ${
                    active ? "bg-white/10 text-stone-100" : "bg-stone-900/5 text-stone-700"
                  }`}
                  aria-label={dict.chat.deleteThread}
                >
                  <Trash2Icon className="size-3.5" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
