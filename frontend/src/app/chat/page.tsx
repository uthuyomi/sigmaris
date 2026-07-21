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
  // デザイン統一 第二段階の /chat 保護(判断根拠は下の AppShell theme 指定の
  // コメント参照)。ユーザーのテーマ設定(settings.theme)は /chat では
  // 意図的に使わず、常にダークで固定する。
  const { locale } = settings;
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

  // /chat 保護(デザイン統一 第二段階): テーマ機構は <html> の .dark クラスで
  // 制御され、AppShell が theme に応じて .dark を付け外しする。AppShell へ
  // theme="dark" を渡すことで、ユーザーが light テーマでも /chat 表示中は常に
  // html.dark=true が維持される。これにより、ChatWorkspace 内のトークン利用
  // 要素(markdown-text/tool-fallback/ui/*)に加え、Radix ポータルで <body>
  // 直下へ描画される Copy ボタンのツールチップ等(ChatWorkspace の .dark
  // サブツリーの外に出る要素)も、<html> 配下として .dark 文脈に入り、確実に
  // ダークで表示される。ページ側の変更はこの theme 指定1点のみに留めた
  // (依頼書「/chat ファイル変更は最小限」)。
  return (
    <AppShell
      locale={locale}
      title={dict.shell.chatTitle}
      description={dict.shell.chatDescription}
      badge={dict.shell.chatBadge}
      theme="dark"
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
