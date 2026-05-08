"use client";
// 役割: クライアント側で動くアシスタントUIのエントリーポイント。


import type { AppendMessage } from "@assistant-ui/core";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAISDKRuntime, AssistantChatTransport } from "@assistant-ui/react-ai-sdk";
import { useChat } from "@ai-sdk/react";
import {
  lastAssistantMessageIsCompleteWithToolCalls,
  type CreateUIMessage,
  type UIMessage,
} from "ai";
import { Thread } from "@/components/thread";
import type { ChatUsageStatus } from "@/lib/chat-usage";
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
    metadata: message.metadata,
  } as CreateUIMessage<UI_MESSAGE>;
};

type AssistantProps = {
  threadId: string;
  initialMessages: UIMessage[];
  locale: AppLocale;
  freeChatUsage: ChatUsageStatus | null;
};

export const Assistant = ({ threadId, initialMessages, locale, freeChatUsage }: AssistantProps) => {
  const initialUserMessageCount = initialMessages.filter((message) => message.role === "user").length;
  const chat = useChat({
    id: threadId,
    messages: initialMessages,
    transport: new AssistantChatTransport({
      api: "/api/chat",
      body: {
        threadId,
      },
    }),
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithToolCalls,
  });

  const runtime = useAISDKRuntime(chat, {
    toCreateMessage,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="h-full min-h-0 min-w-0 overflow-hidden">
        <Thread
          locale={locale}
          freeChatUsage={freeChatUsage}
          initialUserMessageCount={initialUserMessageCount}
        />
      </div>
    </AssistantRuntimeProvider>
  );
};
