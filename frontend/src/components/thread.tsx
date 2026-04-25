"use client";
// 役割: アシスタントとのチャットスレッド表示と入力欄を構成するReactコンポーネント。


import { ComposerAttachments, UserMessageAttachments } from "@/components/attachment";
import { MarkdownText } from "@/components/markdown-text";
import { getDictionary, type AppLocale } from "@/lib/i18n";
import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from "@assistant-ui/react";
import { ArrowDownIcon, ArrowUpIcon, PlusIcon, SquareIcon } from "lucide-react";
import { type FC, useEffect, useRef, useState } from "react";

type ThreadProps = {
  locale: AppLocale;
};

export const Thread: FC<ThreadProps> = ({ locale }) => {
  const dict = getDictionary(locale);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const messages = useAuiState((s) => s.thread.messages);
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const [statusStep, setStatusStep] = useState(0);

  const latestAssistantText = (() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role !== "assistant") continue;
      return message.parts
        .filter((part) => part.type === "text")
        .map((part) => part.text)
        .join("");
    }
    return "";
  })();

  const showPendingStatus = isRunning && latestAssistantText.trim().length === 0;

  const updateScrollState = () => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    const distanceFromBottom =
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    setShowScrollButton(distanceFromBottom > 120);
  };

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollTo({ top: viewport.scrollHeight, behavior });
  };

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    updateScrollState();
    const handleScroll = () => updateScrollState();
    viewport.addEventListener("scroll", handleScroll);

    return () => {
      viewport.removeEventListener("scroll", handleScroll);
    };
  }, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    const distanceFromBottom =
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    const shouldAutoScroll = distanceFromBottom < 160;

    if (shouldAutoScroll) {
      requestAnimationFrame(() => {
        scrollToBottom("auto");
      });
    } else {
      updateScrollState();
    }
  }, [messages]);

  useEffect(() => {
    if (!showPendingStatus) {
      return;
    }

    const timers = [
      window.setTimeout(() => setStatusStep(0), 0),
      window.setTimeout(() => setStatusStep(1), 1200),
      window.setTimeout(() => setStatusStep(2), 3200),
      window.setTimeout(() => setStatusStep(3), 6200),
    ];

    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [showPendingStatus]);

  return (
    <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col bg-transparent">
      <div className="relative flex-1 min-h-0">
        <ThreadPrimitive.Viewport
          ref={viewportRef}
          className="h-full overflow-y-auto px-4 pt-6 pb-44 sm:px-6 sm:pb-48"
        >
          <ThreadWelcome locale={locale} />

          <ThreadPrimitive.Messages>
            {() => <ThreadMessage />}
          </ThreadPrimitive.Messages>
        </ThreadPrimitive.Viewport>

        {showScrollButton ? (
          <button
            type="button"
            onClick={() => scrollToBottom()}
            className="absolute bottom-36 right-6 z-20 inline-flex size-11 items-center justify-center rounded-full border border-white/10 bg-stone-900/90 text-stone-50 shadow-[0_18px_35px_-20px_rgba(0,0,0,0.85)] transition hover:bg-stone-800"
            aria-label="下へ移動"
          >
            <ArrowDownIcon className="size-5" />
          </button>
        ) : null}

        {showPendingStatus ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-32 z-20 flex justify-center px-4 sm:px-6">
            <div className="rounded-full border border-white/10 bg-stone-900/88 px-4 py-2 text-xs tracking-wide text-stone-200 shadow-[0_20px_45px_-35px_rgba(0,0,0,0.9)] backdrop-blur">
              {getPendingStatusLabel(statusStep)}
            </div>
          </div>
        ) : null}

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 px-4 pb-5 pt-10 sm:px-6 sm:pb-6">
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-[linear-gradient(180deg,rgba(43,37,34,0),rgba(43,37,34,0.84)_45%,rgba(43,37,34,0.98)_100%)]" />
          <div className="pointer-events-auto relative">
            <Composer placeholder={dict.chat.inputPlaceholder} />
          </div>
        </div>
      </div>
    </ThreadPrimitive.Root>
  );
};

const ThreadWelcome: FC<ThreadProps> = ({ locale }) => {
  const dict = getDictionary(locale);
  const isEmpty = useAuiState((s) => s.thread.isEmpty);
  if (!isEmpty) return null;

  return (
    <div className="mx-auto my-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-2 pb-24 text-center">
      <h1 className="text-3xl font-semibold text-stone-50">{dict.chat.welcomeTitle}</h1>
      <p className="mt-3 text-base leading-8 text-stone-400">{dict.chat.welcomeBody}</p>
    </div>
  );
};

const ThreadMessage: FC = () => {
  const role = useAuiState((s) => s.message.role);

  return (
    <MessagePrimitive.Root className="mx-auto w-full max-w-3xl py-3" data-role={role}>
      {role === "user" ? <UserMessage /> : <AssistantMessage />}
    </MessagePrimitive.Root>
  );
};

const AssistantMessage: FC = () => {
  const sanitizeAssistantText = (text: string) =>
    text.replace(/^確認中\.\.\.\s*/u, "").replace(/^確認中…\s*/u, "");

  return (
    <div className="max-w-[92%] rounded-[26px] rounded-bl-md bg-white/10 px-4 py-3 text-sm leading-7 text-stone-100 shadow-[0_20px_45px_-35px_rgba(0,0,0,0.9)]">
      <MessagePrimitive.Parts>
        {({ part }) => {
          if (part.type === "text") {
            if (!part.text?.trim()) return null;
            return <MarkdownText preprocess={sanitizeAssistantText} />;
          }
          return null;
        }}
      </MessagePrimitive.Parts>
    </div>
  );
};

const getPendingStatusLabel = (step: number) => {
  if (step >= 3) return "ルート整理中";
  if (step >= 2) return "地図検索中";
  if (step >= 1) return "予定確認中";
  return "処理中";
};

const UserMessage: FC = () => {
  return (
    <div className="ml-auto flex max-w-[88%] flex-col gap-2">
      <MessagePrimitive.Attachments components={{ Attachment: UserMessageAttachments }} />
      <div className="ml-auto rounded-[24px] rounded-br-md bg-[#f4a261] px-4 py-3 text-sm leading-7 text-stone-950">
        <MessagePrimitive.Parts />
      </div>
    </div>
  );
};

const Composer: FC<{ placeholder: string }> = ({ placeholder }) => {
  const isRunning = useAuiState((s) => s.thread.isRunning);

  return (
    <ComposerPrimitive.Root className="mx-auto w-full max-w-3xl">
      <div className="rounded-[30px] border border-white/12 bg-[#2b2522]/95 p-3 text-stone-50 shadow-[0_20px_45px_-35px_rgba(0,0,0,0.55)] backdrop-blur">
        <ComposerPrimitive.Attachments
          components={{
            Attachment: ComposerAttachments,
          }}
        />

        <div className="mt-2 flex items-end gap-2">
          <ComposerPrimitive.AddAttachment
            multiple
            className="inline-flex size-11 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/6 text-stone-200 transition hover:bg-white/12"
          >
            <PlusIcon className="size-5" />
          </ComposerPrimitive.AddAttachment>

          <ComposerPrimitive.Input
            placeholder={placeholder}
            className="min-h-11 w-full resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-stone-400"
            rows={1}
            aria-label="メッセージ"
          />

          {isRunning ? (
            <ComposerPrimitive.Cancel className="inline-flex size-11 shrink-0 items-center justify-center rounded-full bg-[#e76f51] text-white transition hover:bg-[#d95f42]">
              <SquareIcon className="size-4 fill-current" />
            </ComposerPrimitive.Cancel>
          ) : (
            <ComposerPrimitive.Send className="inline-flex size-11 shrink-0 items-center justify-center rounded-full bg-[#e76f51] text-white transition hover:bg-[#d95f42]">
              <ArrowUpIcon className="size-4" />
            </ComposerPrimitive.Send>
          )}
        </div>
      </div>
    </ComposerPrimitive.Root>
  );
};
