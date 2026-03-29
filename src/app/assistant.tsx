"use client";

import type { AppendMessage } from "@assistant-ui/core";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import {
  AssistantChatTransport,
  useChatRuntime,
} from "@assistant-ui/react-ai-sdk";
import {
  lastAssistantMessageIsCompleteWithToolCalls,
  type CreateUIMessage,
  type UIMessage,
} from "ai";
import { Thread } from "@/components/thread";

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

  const hasText = inputParts.some((part) => part.type === "text" && part.text.trim().length > 0);
  const hasFile = inputParts.some((part) => part.type === "image" || part.type === "file");

  if (!hasText && hasFile) {
    inputParts.unshift({
      type: "text",
      text: "添付ファイルを確認して、予定候補を整理してください。",
    });
  }

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

export const Assistant = () => {
  const runtime = useChatRuntime({
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithToolCalls,
    toCreateMessage,
    transport: new AssistantChatTransport({
      api: "/api/chat",
    }),
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="h-full min-h-0">
        <Thread />
      </div>
    </AssistantRuntimeProvider>
  );
};
