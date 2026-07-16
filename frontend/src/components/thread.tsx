"use client";
// 役割: アシスタントとのチャットスレッド表示と入力欄を構成するReactコンポーネント。

import {
  ComposerAttachments,
  UserMessageAttachments,
} from "@/components/attachment";
import { MarkdownText } from "@/components/markdown-text";
import { ToolFallback } from "@/components/tool-fallback";
import {
  parseLatestConfirmationAction,
  removeConfirmationMarkers,
  type ChatConfirmationAction,
} from "@/lib/chat-confirmation";
import { formatAbsoluteDateTime, formatRelativeTime } from "@/lib/format-time";
import type { AppLocale } from "@/lib/i18n";
import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useThreadRuntime,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  PlusIcon,
  SquareIcon,
  XIcon,
} from "lucide-react";
import { type FC, useCallback, useEffect, useRef, useState } from "react";

type ThreadProps = {
  locale: AppLocale;
};

export const Thread: FC<ThreadProps> = ({ locale }) => {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const showScrollButtonRef = useRef(false);
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
  const messageScrollKey = messages
    .map((message, index) => {
      const textLength = message.parts
        .filter((part) => part.type === "text")
        .reduce((total, part) => total + part.text.length, 0);
      return `${message.id ?? index}:${message.role}:${message.parts.length}:${textLength}`;
    })
    .join("|");

  const showPendingStatus =
    isRunning && latestAssistantText.trim().length === 0;

  const updateScrollState = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    if (viewport.scrollLeft !== 0) {
      viewport.scrollLeft = 0;
    }

    const distanceFromBottom =
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    const shouldShow = distanceFromBottom > 120;
    if (showScrollButtonRef.current === shouldShow) return;

    showScrollButtonRef.current = shouldShow;
    setShowScrollButton(shouldShow);
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollTo({ top: viewport.scrollHeight, behavior });
  }, []);

  const resetHorizontalScroll = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport || viewport.scrollLeft === 0) return;
    viewport.scrollLeft = 0;
  }, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    resetHorizontalScroll();
    updateScrollState();
    const handleScroll = () => {
      resetHorizontalScroll();
      updateScrollState();
    };
    const handleTouchStart = (event: TouchEvent) => {
      if (event.touches.length !== 1) {
        touchStartRef.current = null;
        return;
      }

      const touch = event.touches[0];
      touchStartRef.current = { x: touch.clientX, y: touch.clientY };
    };
    const handleTouchMove = (event: TouchEvent) => {
      const start = touchStartRef.current;
      const touch = event.touches[0];
      if (!start || !touch) return;

      const deltaX = touch.clientX - start.x;
      const deltaY = touch.clientY - start.y;
      if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > 8) {
        event.preventDefault();
        resetHorizontalScroll();
      }
    };
    const handleTouchEnd = () => {
      touchStartRef.current = null;
      resetHorizontalScroll();
    };

    viewport.addEventListener("scroll", handleScroll);
    viewport.addEventListener("touchstart", handleTouchStart, {
      passive: true,
    });
    viewport.addEventListener("touchmove", handleTouchMove, { passive: false });
    viewport.addEventListener("touchend", handleTouchEnd);
    viewport.addEventListener("touchcancel", handleTouchEnd);

    return () => {
      viewport.removeEventListener("scroll", handleScroll);
      viewport.removeEventListener("touchstart", handleTouchStart);
      viewport.removeEventListener("touchmove", handleTouchMove);
      viewport.removeEventListener("touchend", handleTouchEnd);
      viewport.removeEventListener("touchcancel", handleTouchEnd);
    };
  }, [resetHorizontalScroll, updateScrollState]);

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
  }, [messageScrollKey, scrollToBottom, updateScrollState]);

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
    <ThreadPrimitive.Root className="chat-thread-surface flex h-full min-h-0 min-w-0 max-w-full touch-pan-y flex-col overflow-hidden overscroll-x-none bg-[#212121] text-[#ececec]">
      <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
        <ThreadPrimitive.Viewport
          ref={viewportRef}
          data-scrollbar-hidden="true"
          className="no-scrollbar scrollbar-hidden h-full min-w-0 max-w-full touch-pan-y overflow-x-hidden overflow-y-auto overscroll-x-none px-4 pt-5 pb-36 sm:px-6 sm:pb-40"
          style={{
            msOverflowStyle: "none",
            scrollbarWidth: "none",
          }}
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
            className="absolute bottom-36 left-1/2 z-20 inline-flex size-9 -translate-x-1/2 items-center justify-center rounded-full border border-white/10 bg-[#2f2f2f] text-[#ececec] shadow-[0_18px_35px_-24px_rgba(0,0,0,0.9)] transition hover:bg-[#3a3a3a]"
            aria-label="最新メッセージへ移動"
          >
            <ArrowDownIcon className="size-5" />
          </button>
        ) : null}

        {showPendingStatus ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-32 z-20 flex justify-center px-4 sm:px-6">
            <div className="rounded-full border border-white/10 bg-[#2f2f2f]/95 px-4 py-2 text-xs text-[#8e8ea0] shadow-[0_20px_45px_-35px_rgba(0,0,0,0.9)] backdrop-blur">
              {getPendingStatusLabel(statusStep)}
            </div>
          </div>
        ) : null}

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 px-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-10 sm:px-6 sm:pb-6">
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-[linear-gradient(180deg,rgba(33,33,33,0),rgba(33,33,33,0.92)_48%,rgba(33,33,33,1)_100%)]" />
          <div className="pointer-events-auto relative">
            <Composer placeholder="シグマリスにメッセージする" />
          </div>
        </div>
      </div>
    </ThreadPrimitive.Root>
  );
};

const ThreadWelcome: FC<Pick<ThreadProps, "locale">> = () => {
  const isEmpty = useAuiState((s) => s.thread.isEmpty);
  if (!isEmpty) return null;

  return (
    <div className="mx-auto my-auto flex min-h-full w-full max-w-[800px] flex-col items-center justify-center px-2 pb-28 text-center">
      <div className="mb-6 flex size-16 items-center justify-center rounded-2xl bg-[#9b59b6] text-3xl font-semibold text-white shadow-[0_24px_80px_-42px_rgba(155,89,182,0.95)]">
        Σ
      </div>
      <h1 className="text-3xl font-semibold tracking-normal text-[#ececec] sm:text-4xl">
        シグマリス
      </h1>
      <p className="mt-3 text-sm leading-7 text-[#8e8ea0] sm:text-base">
        何でも話しかけてください
      </p>
    </div>
  );
};

// メッセージ日時表示機能(docs/sigmaris/phase_ba4_report.md): metadata.
// createdAtの読み取り元は3経路ある(DB再読み込み時はchat-threads.tsが
// backendの真のcreated_atを、ライブ送信中はassistant.tsx/stream-
// translator.tsがクライアント側の捕捉時刻を、それぞれ設定する)。
// 相対表示は他ページと違い秒単位で自動更新しない(15章「チャットUI上の
// 秒数表示を撤去」の教訓通り、tick更新はstreaming描画と競合するため)。
function readCreatedAt(metadata: unknown): string | null {
  if (!metadata || typeof metadata !== "object") return null;
  const value = (metadata as Record<string, unknown>).createdAt;
  return typeof value === "string" ? value : null;
}

const MessageTimestamp: FC<{ align: "left" | "right" }> = ({ align }) => {
  const createdAt = useAuiState((s) => readCreatedAt(s.message.metadata));
  const relative = formatRelativeTime(createdAt);
  if (!relative) return null;
  const absolute = formatAbsoluteDateTime(createdAt);

  return (
    <div
      className={`mt-1 text-xs text-[#8e8ea0] ${align === "right" ? "text-right" : "text-left"}`}
      title={absolute ?? undefined}
    >
      {relative}
    </div>
  );
};

const ThreadMessage: FC = () => {
  const role = useAuiState((s) => s.message.role);

  return (
    <MessagePrimitive.Root
      className="mx-auto w-full max-w-[800px] min-w-0 overflow-visible py-3 sm:py-4"
      data-role={role}
    >
      {role === "user" ? <UserMessage /> : <AssistantMessage />}
    </MessagePrimitive.Root>
  );
};

const AssistantMessage: FC = () => {
  const thread = useThreadRuntime();
  const [isSendingConfirmation, setIsSendingConfirmation] = useState(false);
  const currentMessageId = useAuiState((s) => s.message.id);
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const latestAssistantMessageId = useAuiState((s) => {
    for (let index = s.thread.messages.length - 1; index >= 0; index -= 1) {
      const message = s.thread.messages[index];
      if (message.role === "assistant") {
        return message.id ?? "";
      }
    }
    return "";
  });
  const messageText = useAuiState((s) =>
    s.message.parts
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join(""),
  );
  const confirmationAction =
    currentMessageId === latestAssistantMessageId
      ? parseLatestConfirmationAction(messageText)
      : null;
  const sendConfirmation = (choice: "yes" | "no", action: ChatConfirmationAction) => {
    const label = choice === "yes" ? "実行して" : "キャンセルして";
    const confirmationText = `SHIFT_PILOT_CONFIRM:${choice} ${action.tool}\n${action.title} を${label}。`;
    setIsSendingConfirmation(true);
    try {
      thread.append(confirmationText);
    } catch {
      setIsSendingConfirmation(false);
    }
  };
  const sanitizeAssistantText = (text: string) =>
    text.replace(/^確認中\.\.\.\s*/u, "").replace(/^確認中…\s*/u, "");

  return (
    <div className="grid w-full min-w-0 grid-cols-[28px_minmax(0,1fr)] gap-4 overflow-visible px-0 py-2 text-[15px] leading-7 text-[#ececec] [overflow-wrap:anywhere] sm:grid-cols-[32px_minmax(0,1fr)]">
      <div className="mt-1 inline-flex size-7 items-center justify-center rounded-full bg-[#9b59b6] text-sm font-semibold text-white sm:size-8">
        Σ
      </div>
      <div className="min-w-0">
        <MessagePrimitive.Parts
          components={{
            Text: () => (
              <MarkdownText
                preprocess={(text) =>
                  removeConfirmationMarkers(sanitizeAssistantText(text))
                }
              />
            ),
            tools: {
              Fallback: ToolFallback,
            },
          }}
        />
        {isRunning && currentMessageId === latestAssistantMessageId ? (
          <span className="ml-0.5 inline-block h-5 w-2 translate-y-1 animate-pulse rounded-sm bg-[#ececec]" />
        ) : null}
        {confirmationAction ? (
          <ConfirmationActionCard
            action={confirmationAction}
            disabled={isSendingConfirmation}
            onConfirm={() => sendConfirmation("yes", confirmationAction)}
            onCancel={() => sendConfirmation("no", confirmationAction)}
          />
        ) : null}
        <MessageTimestamp align="left" />
      </div>
    </div>
  );
};

const ConfirmationActionCard: FC<{
  action: ChatConfirmationAction;
  disabled: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}> = ({ action, disabled, onConfirm, onCancel }) => {
  return (
    <div className="mt-3 max-w-xl rounded-2xl border border-white/10 bg-[#2f2f2f] px-4 py-3 text-[#ececec] shadow-[0_18px_45px_-34px_rgba(0,0,0,0.75)]">
      <div className="text-sm font-semibold leading-6">{action.title}</div>
      <p className="mt-1 text-xs leading-5 text-[#8e8ea0]">
        {action.description}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={onConfirm}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-[#9b59b6] px-4 text-sm font-semibold text-white transition hover:bg-[#8e44ad] disabled:cursor-not-allowed disabled:opacity-45"
        >
          <CheckIcon className="size-4" />
          はい
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onCancel}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-white/10 bg-transparent px-4 text-sm font-medium text-[#ececec] transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-45"
        >
          <XIcon className="size-4" />
          いいえ
        </button>
      </div>
    </div>
  );
};

const getPendingStatusLabel = (step: number) => {
  if (step >= 3) return "シグマリスが整理しています";
  if (step >= 2) return "シグマリスが確認しています";
  if (step >= 1) return "シグマリスが考えています";
  return "シグマリスが入力中";
};

const UserMessage: FC = () => {
  return (
    <div className="ml-auto flex max-w-[70%] min-w-0 flex-col gap-2">
      <MessagePrimitive.Attachments
        components={{ Attachment: UserMessageAttachments }}
      />
      <div className="ml-auto min-w-0 overflow-hidden break-words rounded-[1.2rem] bg-[#2f2f2f] px-4 py-3 text-[15px] leading-7 text-[#ececec] [overflow-wrap:anywhere]">
        <MessagePrimitive.Parts />
      </div>
      <MessageTimestamp align="right" />
    </div>
  );
};

const Composer: FC<{ placeholder: string }> = ({ placeholder }) => {
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const composerText = useAuiState((s) => s.composer.text);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const canSend = composerText.trim().length > 0;

  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;

    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
    input.style.overflowY = input.scrollHeight > 200 ? "auto" : "hidden";
  }, [composerText]);

  return (
    <ComposerPrimitive.Root className="mx-auto w-full max-w-[800px] min-w-0">
      <div className="min-w-0 overflow-hidden rounded-[1.5rem] bg-[#2f2f2f] px-3 py-2 text-[#ececec] shadow-[0_18px_50px_-32px_rgba(0,0,0,0.9)] ring-1 ring-white/10 focus-within:ring-white/20">
        <ComposerPrimitive.Attachments
          components={{
            Attachment: ComposerAttachments,
          }}
        />

        <div className="flex min-h-12 items-end gap-2">
          <ComposerPrimitive.AddAttachment
            multiple
            className="mb-0.5 inline-flex size-9 shrink-0 items-center justify-center rounded-full text-[#b4b4b4] transition hover:bg-white/10 hover:text-[#ececec] disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="ファイルを追加"
          >
            <PlusIcon className="size-5" />
          </ComposerPrimitive.AddAttachment>

          <ComposerPrimitive.Input
            ref={inputRef}
            placeholder={placeholder}
            submitMode="enter"
            minRows={1}
            maxRows={8}
            className="max-h-[200px] min-h-11 w-full resize-none overflow-y-hidden bg-transparent px-1 py-2.5 text-[15px] leading-6 text-[#ececec] outline-none placeholder:text-[#8e8ea0]"
            rows={1}
            aria-label="メッセージ"
          />

          {isRunning ? (
            <ComposerPrimitive.Cancel
              className="mb-1 inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-[#ececec] text-[#212121] transition hover:bg-white"
              aria-label="生成を停止"
            >
              <SquareIcon className="size-4 fill-current" />
            </ComposerPrimitive.Cancel>
          ) : (
            <ComposerPrimitive.Send
              disabled={!canSend}
              className="mb-1 inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-[#9b59b6] text-white transition hover:bg-[#8e44ad] disabled:cursor-not-allowed disabled:bg-[#4a4a4a] disabled:text-[#8e8ea0]"
              aria-label="送信"
            >
              <ArrowUpIcon className="size-4" />
            </ComposerPrimitive.Send>
          )}
        </div>
      </div>
    </ComposerPrimitive.Root>
  );
};
