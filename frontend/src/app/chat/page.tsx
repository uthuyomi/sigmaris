// 役割: チャット画面を表示するNext.jsページ。

import { type UIMessage } from "ai";
import { redirect } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { ChatWorkspace } from "@/components/chat-workspace";
import {
  createChatThread,
  getChatThread,
  listChatMessages,
  listChatThreads,
} from "@/lib/chat-threads";
import { getDictionary } from "@/lib/i18n";
import { readShellSettings } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";

type ChatPageProps = {
  searchParams?: Promise<{
    thread?: string;
  }>;
};

export default async function ChatPage({ searchParams }: ChatPageProps) {
  const user = await requireUser("/chat");
  const params = searchParams ? await searchParams : undefined;
  const requestedThreadId = params?.thread;

  const [settings, threads] = await Promise.all([
    readShellSettings(user.id),
    listChatThreads(user.id),
  ]);
  const { locale, theme } = settings;
  const dict = getDictionary(locale);

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

  const initialMessages = (await listChatMessages(user.id, selectedThread.id)) as UIMessage[];

  return (
    <AppShell
      locale={locale}
      title={dict.shell.chatTitle}
      description={dict.shell.chatDescription}
      badge={dict.shell.chatBadge}
      theme={theme}
      fitViewport
    >
      <ChatWorkspace
        locale={locale}
        threads={threads}
        activeThreadId={selectedThread.id}
        activeThreadTitle={selectedThread.title}
        initialMessages={initialMessages}
        assistantLabel={dict.chat.assistant}
      />
    </AppShell>
  );
}
