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
  useComposerRuntime,
} from "@assistant-ui/react";
import { ArrowDownIcon, ArrowUpIcon, FileTextIcon, PlusIcon, SquareIcon } from "lucide-react";
import { type FC, useCallback, useEffect, useRef, useState } from "react";

type ThreadProps = {
  locale: AppLocale;
};

export const Thread: FC<ThreadProps> = ({ locale }) => {
  const dict = getDictionary(locale);
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

  const showPendingStatus = isRunning && latestAssistantText.trim().length === 0;

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
    viewport.addEventListener("touchstart", handleTouchStart, { passive: true });
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
            className="absolute bottom-36 right-4 z-20 inline-flex size-10 items-center justify-center rounded-full border border-stone-900/10 bg-white text-stone-900 shadow-[0_18px_35px_-24px_rgba(0,0,0,0.55)] transition hover:bg-stone-100 dark:border-white/10 dark:bg-[#2f2f2f] dark:text-white dark:hover:bg-[#3a3a3a] sm:right-6"
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
      <h1 className="text-2xl font-semibold text-stone-950 dark:text-stone-50 sm:text-3xl">{dict.chat.welcomeTitle}</h1>
      <p className="mt-3 text-sm leading-7 text-stone-500 dark:text-stone-400 sm:text-base sm:leading-8">{dict.chat.welcomeBody}</p>
    </div>
  );
};

const ThreadMessage: FC = () => {
  const role = useAuiState((s) => s.message.role);

  return (
    <MessagePrimitive.Root className="mx-auto w-full max-w-3xl min-w-0 overflow-hidden py-2 sm:py-3" data-role={role}>
      {role === "user" ? <UserMessage /> : <AssistantMessage />}
    </MessagePrimitive.Root>
  );
};

const AssistantMessage: FC = () => {
  const sanitizeAssistantText = (text: string) =>
    text.replace(/^確認中\.\.\.\s*/u, "").replace(/^確認中…\s*/u, "");

  return (
    <div className="w-full min-w-0 overflow-hidden break-words px-1 py-2 text-sm leading-7 text-stone-900 [overflow-wrap:anywhere] dark:text-stone-100 sm:px-3">
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
    <div className="ml-auto flex max-w-[92%] min-w-0 flex-col gap-2 sm:max-w-[78%]">
      <MessagePrimitive.Attachments components={{ Attachment: UserMessageAttachments }} />
      <div className="ml-auto min-w-0 overflow-hidden break-words rounded-[22px] bg-[#f4f4f4] px-4 py-3 text-sm leading-7 text-stone-950 [overflow-wrap:anywhere] dark:bg-[#2f2f2f] dark:text-stone-100">
        <MessagePrimitive.Parts />
      </div>
    </div>
  );
};

const Composer: FC<{ placeholder: string }> = ({ placeholder }) => {
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
  const [selectedTemplateId, setSelectedTemplateId] = useState<PromptTemplateId>(
    promptTemplates[0].id,
  );
  const [showTemplatePreview, setShowTemplatePreview] = useState(false);

  const selectedTemplate =
    promptTemplates.find((template) => template.id === selectedTemplateId) ?? promptTemplates[0];

  useEffect(() => {
    if (latestAssistantMessageKeyRef.current === latestAssistantMessageKey) return;

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
            onChange={(event) => {
              setSelectedTemplateId(event.target.value as PromptTemplateId);
              setShowTemplatePreview(true);
            }}
            onFocus={() => setShowTemplatePreview(true)}
            className="min-h-10 flex-1 rounded-xl border border-stone-900/10 bg-stone-50 px-3 text-sm text-stone-900 outline-none transition hover:bg-stone-100 focus:border-stone-900/30 dark:border-white/10 dark:bg-white/6 dark:text-stone-100 dark:hover:bg-white/10"
            aria-describedby={showTemplatePreview ? "prompt-template-preview" : undefined}
          >
            {promptTemplates.map((template) => (
              <option key={template.id} value={template.id} className="bg-white text-stone-900">
                {template.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleInsertTemplate}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-stone-900/10 bg-stone-50 px-4 text-sm font-medium text-stone-800 transition hover:bg-stone-100 focus:outline-none focus:ring-2 focus:ring-stone-900/15 dark:border-white/10 dark:bg-white/6 dark:text-stone-200 dark:hover:bg-white/10"
            aria-describedby={showTemplatePreview ? "prompt-template-preview" : undefined}
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
            className="inline-flex size-10 shrink-0 items-center justify-center rounded-full text-stone-500 transition hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-white/10 sm:size-11"
          >
            <PlusIcon className="size-5" />
          </ComposerPrimitive.AddAttachment>

          <ComposerPrimitive.Input
            ref={inputRef}
            placeholder={placeholder}
            className="min-h-11 w-full resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-stone-400"
            rows={1}
            aria-label="メッセージ"
          />

          {isRunning ? (
            <ComposerPrimitive.Cancel className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-stone-900 text-white transition hover:bg-stone-700 sm:size-11">
              <SquareIcon className="size-4 fill-current" />
            </ComposerPrimitive.Cancel>
          ) : (
            <ComposerPrimitive.Send className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-stone-900 text-white transition hover:bg-stone-700 sm:size-11">
              <ArrowUpIcon className="size-4" />
            </ComposerPrimitive.Send>
          )}
        </div>
      </div>
    </ComposerPrimitive.Root>
  );
};

const promptTemplates = [
  {
    id: "extract-shift-image",
    label: "シフト表・画像から予定抽出",
    text: `添付したシフト表・予定表から予定候補を抽出してください。
必要ならタイトル、日付、開始時刻、終了時刻、場所、補足を整理してください。
不明なところは勝手に確定せず、確認項目として出してください。`,
  },
  {
    id: "import-google-sheets",
    label: "Sheetsから予定取り込み",
    text: `この Google Sheets から予定候補を読み取ってください。

URL: 【ここに入力: Google Sheets URL】

読み取った内容を、日付・開始時刻・終了時刻・タイトル・場所・補足に整理してください。
登録前に確認できる一覧で出してください。`,
  },
  {
    id: "create-event-manual",
    label: "予定を手入力で作成",
    text: `次の予定をカレンダーに登録したいです。

タイトル: 【ここに入力: 予定名】
日付: 【ここに入力: 日付】
開始時刻: 【ここに入力: 開始時刻】
終了時刻: 【ここに入力: 終了時刻】
場所: 【ここに入力: 住所または施設名】
補足: 【ここに入力: メモ】

登録前に内容を確認してください。`,
  },
  {
    id: "check-day-events",
    label: "今日・明日の予定確認",
    text: `【ここに入力: 今日 / 明日 / 日付】の予定を確認してください。
アプリ内の予定と Google Calendar の予定を見て、時間順に整理してください。
移動が必要そうな予定があれば教えてください。`,
  },
  {
    id: "plan-travel-time",
    label: "移動時間を計算",
    text: `次の予定に間に合う移動計画を作ってください。

出発地: 【ここに入力: 自宅 / 現在地 / 保存済み地点名 / 住所】
目的地: 【ここに入力: 住所または施設名】
到着したい時刻: 【ここに入力: 日付と時刻】
移動手段: 【ここに入力: 車 / 自転車 / 徒歩】

出発時刻、所要時間、注意点を出してください。`,
  },
] as const;

type PromptTemplateId = (typeof promptTemplates)[number]["id"];
