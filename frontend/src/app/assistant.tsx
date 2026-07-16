"use client";
// 役割: クライアント側で動くアシスタントUIのエントリーポイント。


import type { AppendMessage } from "@assistant-ui/core";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAISDKRuntime, AssistantChatTransport } from "@assistant-ui/react-ai-sdk";
import { useChat } from "@ai-sdk/react";
import {
  type CreateUIMessage,
  type UIMessage,
} from "ai";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef } from "react";
import { Thread } from "@/components/thread";
import type { AppLocale } from "@/lib/i18n";

const toCreateMessage = <UI_MESSAGE extends UIMessage = UIMessage>(
  message: AppendMessage,
): CreateUIMessage<UI_MESSAGE> => {
  const inputParts = [
    ...message.content.filter((content) => content.type !== "file"),
    ...(message.attachments?.flatMap((attachment) =>
      attachment.content.map((content) => ({
        ...content,
        filename: attachment.name,
      })),
    ) ?? []),
  ];

  const parts: UIMessage["parts"] = inputParts.map((part) => {
    switch (part.type) {
      case "text":
        return {
          type: "text",
          text: part.text,
        };
      case "image":
        return {
          type: "file",
          url: part.image,
          filename: part.filename,
          mediaType: "image/png",
        };
      case "file":
        return {
          type: "file",
          url: part.data,
          mediaType: part.mimeType,
          filename: part.filename,
        };
      default:
        throw new Error(`Unsupported part type: ${part.type}`);
    }
  });

  return {
    role: message.role,
    parts,
    // メッセージ日時表示機能(docs/sigmaris/phase_ba4_report.md): 送信の
    // 瞬間にクライアント側で捕捉した時刻。DB再読み込み後はbackendの真の
    // created_at(chat-threads.ts経由)に置き換わる — この値はライブ表示
    // 専用の近似値。
    metadata: { ...message.metadata, createdAt: new Date().toISOString() },
  } as CreateUIMessage<UI_MESSAGE>;
};

type AssistantProps = {
  threadId: string;
  initialMessages: UIMessage[];
  locale: AppLocale;
};

export const Assistant = ({ threadId, initialMessages, locale }: AssistantProps) => {
  const router = useRouter();
  const wasRunningRef = useRef(false);
  const transport = useMemo(
    () =>
      new AssistantChatTransport({
        api: "/api/chat",
        body: {
          threadId,
        },
      }),
    [threadId],
  );
  const chat = useChat({
    id: threadId,
    messages: initialMessages,
    transport,
    experimental_throttle: 50,
  });

  useEffect(() => {
    const isRunning = chat.status === "submitted" || chat.status === "streaming";
    if (isRunning) {
      wasRunningRef.current = true;
      return;
    }

    if (chat.status === "ready" && wasRunningRef.current) {
      wasRunningRef.current = false;
      router.refresh();
    }
  }, [chat.status, router]);

  const runtime = useAISDKRuntime(chat, {
    toCreateMessage,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="h-full min-h-0 min-w-0 overflow-hidden">
        <Thread locale={locale} />
      </div>
    </AssistantRuntimeProvider>
  );
};
