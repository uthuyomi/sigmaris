import { type UIMessage } from "ai";
import { redirect } from "next/navigation";
import { Assistant } from "@/app/assistant";
import { AppShell } from "@/components/app-shell";
import { ChatThreadSidebar } from "@/components/chat-thread-sidebar";
import {
  createChatThread,
  getChatThread,
  listChatMessages,
  listChatThreads,
} from "@/lib/chat-threads";
import { getDictionary } from "@/lib/i18n";
import { readUserLocale } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";

type ChatPageProps = {
  searchParams?: Promise<{
    thread?: string;
  }>;
};

export default async function ChatPage({ searchParams }: ChatPageProps) {
  const user = await requireUser("/chat");
  const locale = await readUserLocale(user.id);
  const dict = getDictionary(locale);
  const params = searchParams ? await searchParams : undefined;
  const requestedThreadId = params?.thread;

  let threads = await listChatThreads(user.id);
  if (!threads.length) {
    const created = await createChatThread(user.id);
    redirect(`/chat?thread=${created.id}`);
  }

  let selectedThreadId = requestedThreadId ?? threads[0]?.id;
  const selectedThread = selectedThreadId ? await getChatThread(user.id, selectedThreadId) : null;

  if (!selectedThread) {
    selectedThreadId = threads[0]?.id;
    if (!selectedThreadId) {
      const created = await createChatThread(user.id);
      redirect(`/chat?thread=${created.id}`);
    }

    redirect(`/chat?thread=${selectedThreadId}`);
  }

  threads = await listChatThreads(user.id);
  const initialMessages = (await listChatMessages(user.id, selectedThread.id)) as UIMessage[];

  return (
    <AppShell
      locale={locale}
      title={dict.shell.chatTitle}
      description={dict.shell.chatDescription}
      badge={dict.shell.chatBadge}
      fitViewport
    >
      <section className="grid h-full min-h-0 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <ChatThreadSidebar
          locale={locale}
          threads={threads}
          activeThreadId={selectedThread.id}
        />

        <section className="min-h-0 overflow-hidden rounded-[32px] border border-stone-900/10 bg-[linear-gradient(180deg,_rgba(35,31,32,0.98),_rgba(54,48,42,0.94))] shadow-[0_30px_90px_-50px_rgba(28,25,23,0.9)]">
          <div className="border-b border-white/10 px-5 py-5 text-stone-50 sm:px-6">
            <p className="text-xs uppercase tracking-[0.3em] text-stone-400">
              {dict.chat.assistant}
            </p>
            <h2 className="mt-2 text-lg font-semibold">{selectedThread.title}</h2>
          </div>
          <div className="h-[calc(100%-5.25rem)] min-h-0">
            <Assistant threadId={selectedThread.id} initialMessages={initialMessages} locale={locale} />
          </div>
        </section>
      </section>
    </AppShell>
  );
}
