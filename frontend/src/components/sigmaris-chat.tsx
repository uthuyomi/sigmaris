"use client";

import { ArrowUpIcon, LoaderCircleIcon } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { sendOrchestratorMessage } from "@/lib/orchestrator/client";
import type { OrchestratorMessage } from "@/lib/orchestrator/types";

export function SigmarisChat() {
  const [messages, setMessages] = useState<OrchestratorMessage[]>([]);
  const [threadId, setThreadId] = useState<string>();
  const [input, setInput] = useState("");
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const canSubmit = useMemo(
    () => input.trim().length > 0 && !submitting,
    [input, submitting],
  );

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;

    const userMessage: OrchestratorMessage = {
      role: "user",
      content: input.trim(),
    };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setInput("");
    setError(undefined);
    setSubmitting(true);

    try {
      const result = await sendOrchestratorMessage({
        messages: nextMessages,
        threadId,
      });
      setThreadId(result.thread_id);
      setMessages((current) => [
        ...current,
        { role: "assistant", content: result.text },
      ]);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "応答を取得できませんでした。",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-3xl border border-stone-900/10 bg-white shadow-sm dark:border-white/10 dark:bg-[#2f2f2f]">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-6 sm:px-8">
        {messages.length === 0 ? (
          <div className="mx-auto flex h-full max-w-xl flex-col items-center justify-center text-center">
            <p className="text-2xl font-semibold">何を一緒に整理しましょうか？</p>
            <p className="mt-3 text-sm leading-7 text-stone-500 dark:text-stone-400">
              現在は予定確認、カレンダー登録、移動計画をスケジュールエージェントと連携して扱えます。
            </p>
          </div>
        ) : (
          messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={
                message.role === "user"
                  ? "ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl bg-stone-100 px-4 py-3 text-sm leading-7 dark:bg-white/10"
                  : "mr-auto max-w-3xl whitespace-pre-wrap px-1 py-2 text-sm leading-7"
              }
            >
              {message.content}
            </div>
          ))
        )}

        {submitting ? (
          <div className="inline-flex items-center gap-2 text-sm text-stone-500">
            <LoaderCircleIcon className="size-4 animate-spin" />
            予定を確認して、シグマリスの言葉に整えています
          </div>
        ) : null}
      </div>

      <form
        onSubmit={handleSubmit}
        className="border-t border-stone-900/10 p-3 dark:border-white/10 sm:p-4"
      >
        {error ? (
          <p className="mb-3 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-400/10 dark:text-red-200">
            {error}
          </p>
        ) : null}
        <div className="flex items-end gap-2 rounded-2xl border border-stone-900/10 bg-stone-50 p-2 dark:border-white/10 dark:bg-white/5">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            rows={2}
            maxLength={20_000}
            placeholder="明日の予定を教えて"
            className="min-h-12 flex-1 resize-none bg-transparent px-3 py-2 text-sm outline-none"
          />
          <button
            type="submit"
            disabled={!canSubmit}
            aria-label="送信"
            className="inline-flex size-11 shrink-0 items-center justify-center rounded-full bg-stone-950 text-white disabled:opacity-40 dark:bg-white dark:text-stone-950"
          >
            <ArrowUpIcon className="size-4" />
          </button>
        </div>
      </form>
    </div>
  );
}
