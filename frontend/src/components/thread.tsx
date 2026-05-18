"use client";
// 役割: アシスタントとのチャットスレッド表示と入力欄を構成するReactコンポーネント。

import {
  ComposerAttachments,
  UserMessageAttachments,
} from "@/components/attachment";
import { MarkdownText } from "@/components/markdown-text";
import { promptTemplates } from "@/components/thread-prompt-templates";
import {
  parseLatestConfirmationAction,
  removeConfirmationMarkers,
  type ChatConfirmationAction,
} from "@/lib/chat-confirmation";
import { getDictionary, type AppLocale } from "@/lib/i18n";
import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useComposerRuntime,
  useThreadRuntime,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  CreditCardIcon,
  FileTextIcon,
  PlusIcon,
  SquareIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { type FC, useCallback, useEffect, useRef, useState } from "react";
import type { ChatUsageStatus } from "@/lib/chat-usage";
import { PRO_MONTHLY_PRICE_JPY } from "@/lib/stripe";

type ThreadProps = {
  locale: AppLocale;
  freeChatUsage: ChatUsageStatus | null;
  initialUserMessageCount: number;
};

export const Thread: FC<ThreadProps> = ({ locale, freeChatUsage, initialUserMessageCount }) => {
  const dict = getDictionary(locale);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const showScrollButtonRef = useRef(false);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const messages = useAuiState((s) => s.thread.messages);
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const [statusStep, setStatusStep] = useState(0);
  const currentUserMessageCount = messages.filter((message) => message.role === "user").length;
  const usedChatCount = freeChatUsage
    ? freeChatUsage.used + Math.max(0, currentUserMessageCount - initialUserMessageCount)
    : 0;
  const chatLimitReached = Boolean(freeChatUsage && usedChatCount >= freeChatUsage.limit);
  const remainingChatCount = freeChatUsage
    ? Math.max(0, freeChatUsage.limit - usedChatCount)
    : null;

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
    <ThreadPrimitive.Root className="chat-thread-surface flex h-full min-h-0 min-w-0 max-w-full touch-pan-y flex-col overflow-hidden overscroll-x-none bg-white dark:bg-[#212121]">
      <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
        <ThreadPrimitive.Viewport
          ref={viewportRef}
          data-scrollbar-hidden="true"
          className="no-scrollbar scrollbar-hidden h-full min-w-0 max-w-full touch-pan-y overflow-x-hidden overflow-y-auto overscroll-x-none px-3 pt-5 pb-44 sm:px-6 sm:pb-48"
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
            className="absolute bottom-36 left-1/2 z-20 inline-flex size-10 -translate-x-1/2 items-center justify-center rounded-full border border-stone-900/10 bg-white text-stone-900 shadow-[0_18px_35px_-24px_rgba(0,0,0,0.55)] transition hover:bg-stone-100 dark:border-white/10 dark:bg-[#2f2f2f] dark:text-white dark:hover:bg-[#3a3a3a]"
            aria-label="下へ移動"
          >
            <ArrowDownIcon className="size-5" />
          </button>
        ) : null}

        {showPendingStatus ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-32 z-20 flex justify-center px-4 sm:px-6">
            <div className="rounded-full border border-stone-900/10 bg-white/95 px-4 py-2 text-xs tracking-wide text-stone-600 shadow-[0_20px_45px_-35px_rgba(0,0,0,0.6)] backdrop-blur dark:border-white/10 dark:bg-[#2f2f2f]/95 dark:text-stone-300">
              {getPendingStatusLabel(statusStep)}
            </div>
          </div>
        ) : null}

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 px-3 pb-4 pt-10 sm:px-6 sm:pb-6">
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-[linear-gradient(180deg,rgba(255,255,255,0),rgba(255,255,255,0.92)_48%,rgba(255,255,255,1)_100%)] dark:bg-[linear-gradient(180deg,rgba(33,33,33,0),rgba(33,33,33,0.92)_48%,rgba(33,33,33,1)_100%)]" />
          <div className="pointer-events-auto relative">
            {freeChatUsage ? (
              <ChatLimitNotice
                limit={freeChatUsage.limit}
                remaining={remainingChatCount ?? 0}
                reached={chatLimitReached}
              />
            ) : null}
            <Composer
              placeholder={dict.chat.inputPlaceholder}
              disabled={chatLimitReached}
            />
          </div>
        </div>
      </div>
    </ThreadPrimitive.Root>
  );
};

const ThreadWelcome: FC<Pick<ThreadProps, "locale">> = ({ locale }) => {
  const dict = getDictionary(locale);
  const isEmpty = useAuiState((s) => s.thread.isEmpty);
  const composerText = useAuiState((s) => s.composer.text);
  const composer = useComposerRuntime();
  if (!isEmpty) return null;

  const insertTemplate = (template: PromptTemplate) => {
    const nextText = composerText.trim()
      ? `${composerText.trimEnd()}\n\n${template.text}`
      : template.text;

    composer.setText(nextText);
  };

  return (
    <div className="mx-auto my-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-2 pb-28 text-center">
      <h1 className="text-2xl font-semibold text-stone-950 dark:text-stone-50 sm:text-3xl">
        {dict.chat.welcomeTitle}
      </h1>
      <p className="mt-3 text-sm leading-7 text-stone-500 dark:text-stone-400 sm:text-base sm:leading-8">
        {dict.chat.welcomeBody}
      </p>

      <div className="mt-8 flex flex-wrap justify-center gap-2.5">
        {promptTemplates.map((template) => (
          <button
            key={template.id}
            type="button"
            onClick={() => insertTemplate(template)}
            className="inline-flex max-w-full items-center rounded-full border border-stone-900/10 bg-stone-50 px-4 py-2.5 text-sm font-medium text-stone-800 shadow-[0_14px_35px_-30px_rgba(28,25,23,0.75)] transition hover:-translate-y-0.5 hover:border-stone-900/18 hover:bg-white focus:outline-none focus:ring-2 focus:ring-stone-900/15 dark:border-white/10 dark:bg-white/6 dark:text-stone-200 dark:hover:border-white/18 dark:hover:bg-white/10"
          >
            <span className="truncate">{template.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

const ThreadMessage: FC = () => {
  const role = useAuiState((s) => s.message.role);

  return (
    <MessagePrimitive.Root
      className="mx-auto w-full max-w-3xl min-w-0 overflow-hidden py-2 sm:py-3"
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
    <div className="w-full min-w-0 overflow-hidden break-words px-1 py-2 text-sm leading-7 text-stone-900 [overflow-wrap:anywhere] dark:text-stone-100 sm:px-3">
      <MessagePrimitive.Parts>
        {({ part }) => {
          if (part.type === "text") {
            if (!part.text?.trim()) return null;
            return (
              <MarkdownText
                preprocess={(text) =>
                  removeConfirmationMarkers(sanitizeAssistantText(text))
                }
              />
            );
          }
          return null;
        }}
      </MessagePrimitive.Parts>
      {confirmationAction ? (
        <ConfirmationActionCard
          action={confirmationAction}
          disabled={isSendingConfirmation}
          onConfirm={() => sendConfirmation("yes", confirmationAction)}
          onCancel={() => sendConfirmation("no", confirmationAction)}
        />
      ) : null}
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
    <div className="mt-3 max-w-xl rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-3 text-stone-900 shadow-[0_18px_45px_-34px_rgba(28,25,23,0.55)] dark:border-white/10 dark:bg-white/6 dark:text-stone-100">
      <div className="text-sm font-semibold leading-6">{action.title}</div>
      <p className="mt-1 text-xs leading-5 text-stone-600 dark:text-stone-300">
        {action.description}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={onConfirm}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-stone-950 px-4 text-sm font-semibold text-white transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:opacity-45 dark:bg-white dark:text-stone-950 dark:hover:bg-stone-200"
        >
          <CheckIcon className="size-4" />
          はい
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onCancel}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-stone-900/10 bg-white px-4 text-sm font-medium text-stone-800 transition hover:bg-stone-100 disabled:cursor-not-allowed disabled:opacity-45 dark:border-white/10 dark:bg-transparent dark:text-stone-200 dark:hover:bg-white/10"
        >
          <XIcon className="size-4" />
          いいえ
        </button>
      </div>
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
    <div className="ml-auto flex max-w-[92%] min-w-0 flex-col gap-2 sm:max-w-[78%]">
      <MessagePrimitive.Attachments
        components={{ Attachment: UserMessageAttachments }}
      />
      <div className="ml-auto min-w-0 overflow-hidden break-words rounded-[22px] bg-[#f4f4f4] px-4 py-3 text-sm leading-7 text-stone-950 [overflow-wrap:anywhere] dark:bg-[#2f2f2f] dark:text-stone-100">
        <MessagePrimitive.Parts />
      </div>
    </div>
  );
};

const ChatLimitNotice: FC<{ limit: number; remaining: number; reached: boolean }> = ({
  limit,
  remaining,
  reached,
}) => {
  const price = PRO_MONTHLY_PRICE_JPY.toLocaleString("ja-JP");

  return (
    <div className="mb-3 rounded-2xl border border-amber-400/80 bg-amber-50 px-4 py-3 text-sm text-amber-950 shadow-[0_22px_60px_-34px_rgba(120,53,15,0.9)] ring-1 ring-amber-200/80 dark:border-amber-300/35 dark:bg-amber-300/12 dark:text-amber-50 dark:ring-amber-300/15">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="mb-1 inline-flex rounded-full bg-amber-200/80 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-amber-950 dark:bg-amber-200/20 dark:text-amber-100">
            Free limit
          </div>
          <p className="text-base font-semibold leading-6">
            {reached
              ? `無料チャット上限 ${limit} 回に達しました。`
              : `無料チャットは残り ${remaining} / ${limit} 回です。`}
          </p>
          <p className="mt-1 text-xs leading-5 text-amber-900/85 dark:text-amber-100/80">
            {reached
              ? `このまま続ける場合は、ShiftPilotAI Proが月額${price}円です。`
              : `上限後も使う場合は、Proプランが月額${price}円です。`}
          </p>
        </div>
        <Link
          href="/settings"
          className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-xl bg-stone-950 px-5 text-sm font-semibold text-white shadow-[0_16px_35px_-24px_rgba(0,0,0,0.9)] transition hover:bg-stone-800 focus:outline-none focus:ring-2 focus:ring-stone-900/20 dark:bg-white dark:text-stone-950 dark:hover:bg-stone-200"
        >
          <CreditCardIcon className="size-4" />
          Proプランを見る
        </Link>
      </div>
    </div>
  );
};

const Composer: FC<{ placeholder: string; disabled: boolean }> = ({ placeholder, disabled }) => {
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const latestAssistantMessageKey = useAuiState((s) => {
    for (let index = s.thread.messages.length - 1; index >= 0; index -= 1) {
      const message = s.thread.messages[index];
      if (message.role === "assistant") {
        return `${message.id ?? index}:${message.parts.length}`;
      }
    }
    return "";
  });
  const composer = useComposerRuntime();
  const composerText = useAuiState((s) => s.composer.text);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const latestAssistantMessageKeyRef = useRef(latestAssistantMessageKey);
  const [selectedTemplateId, setSelectedTemplateId] =
    useState<PromptTemplateId>(promptTemplates[0].id);
  const [showTemplatePreview, setShowTemplatePreview] = useState(false);

  const selectedTemplate =
    promptTemplates.find((template) => template.id === selectedTemplateId) ??
    promptTemplates[0];

  useEffect(() => {
    if (latestAssistantMessageKeyRef.current === latestAssistantMessageKey)
      return;

    latestAssistantMessageKeyRef.current = latestAssistantMessageKey;
    if (latestAssistantMessageKey) {
      window.setTimeout(() => {
        setShowTemplatePreview(false);
      }, 0);
    }
  }, [latestAssistantMessageKey]);

  const handleInsertTemplate = () => {
    const nextText = composerText.trim()
      ? `${composerText.trimEnd()}\n\n${selectedTemplate.text}`
      : selectedTemplate.text;

    composer.setText(nextText);
    setShowTemplatePreview(false);
    requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
  };

  return (
    <ComposerPrimitive.Root className="mx-auto w-full max-w-3xl min-w-0">
      <div className="min-w-0 overflow-hidden rounded-[26px] border border-stone-900/12 bg-white p-2 text-stone-950 shadow-[0_18px_50px_-32px_rgba(0,0,0,0.55)] dark:border-white/12 dark:bg-[#2f2f2f] dark:text-stone-100 sm:p-3">
        <ComposerPrimitive.Attachments
          components={{
            Attachment: ComposerAttachments,
          }}
        />

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="sr-only" htmlFor="prompt-template-select">
            プロンプトテンプレート
          </label>
          <select
            id="prompt-template-select"
            value={selectedTemplateId}
            disabled={disabled}
            onChange={(event) => {
              setSelectedTemplateId(event.target.value as PromptTemplateId);
              setShowTemplatePreview(true);
            }}
            onFocus={() => setShowTemplatePreview(true)}
            className="min-h-10 flex-1 rounded-xl border border-stone-900/10 bg-stone-50 px-3 text-sm text-stone-900 outline-none transition hover:bg-stone-100 focus:border-stone-900/30 dark:border-white/10 dark:bg-white/6 dark:text-stone-100 dark:hover:bg-white/10"
            aria-describedby={
              showTemplatePreview ? "prompt-template-preview" : undefined
            }
          >
            {promptTemplates.map((template) => (
              <option
                key={template.id}
                value={template.id}
                className="bg-white text-stone-900"
              >
                {template.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleInsertTemplate}
            disabled={disabled}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-stone-900/10 bg-stone-50 px-4 text-sm font-medium text-stone-800 transition hover:bg-stone-100 focus:outline-none focus:ring-2 focus:ring-stone-900/15 dark:border-white/10 dark:bg-white/6 dark:text-stone-200 dark:hover:bg-white/10"
            aria-describedby={
              showTemplatePreview ? "prompt-template-preview" : undefined
            }
          >
            <FileTextIcon className="size-4" />
            挿入
          </button>
        </div>

        {showTemplatePreview ? (
          <div
            id="prompt-template-preview"
            className="mt-2 max-h-28 overflow-y-auto whitespace-pre-wrap rounded-2xl border border-stone-900/10 bg-stone-50 px-3 py-2 text-xs leading-5 text-stone-600 dark:border-white/10 dark:bg-white/6 dark:text-stone-300"
          >
            {selectedTemplate.text}
          </div>
        ) : null}

        <div className="mt-2 flex items-end gap-2">
          <ComposerPrimitive.AddAttachment
            multiple
            disabled={disabled}
            className="inline-flex size-10 shrink-0 items-center justify-center rounded-full text-stone-500 transition hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-white/10 sm:size-11"
          >
            <PlusIcon className="size-5" />
          </ComposerPrimitive.AddAttachment>

          <ComposerPrimitive.Input
            ref={inputRef}
            placeholder={placeholder}
            disabled={disabled}
            className="min-h-11 w-full resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-stone-400"
            rows={1}
            aria-label="メッセージ"
          />

          {isRunning ? (
            <ComposerPrimitive.Cancel className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-stone-900 text-white transition hover:bg-stone-700 sm:size-11">
              <SquareIcon className="size-4 fill-current" />
            </ComposerPrimitive.Cancel>
          ) : (
            <ComposerPrimitive.Send
              disabled={disabled}
              className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-stone-900 text-white transition hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-40 sm:size-11"
            >
              <ArrowUpIcon className="size-4" />
            </ComposerPrimitive.Send>
          )}
        </div>
      </div>
    </ComposerPrimitive.Root>
  );
};

type PromptTemplate = (typeof promptTemplates)[number];
type PromptTemplateId = (typeof promptTemplates)[number]["id"];
