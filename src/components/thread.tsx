import { MarkdownText } from "@/components/markdown-text";
import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from "@assistant-ui/react";
import { ArrowUpIcon, SquareIcon } from "lucide-react";
import type { FC } from "react";

export const Thread: FC = () => {
  return (
    <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col bg-transparent">
      <ThreadPrimitive.Viewport className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 pt-4">
        <ThreadWelcome />

        <ThreadPrimitive.Messages>
          {() => <ThreadMessage />}
        </ThreadPrimitive.Messages>

        <div className="mt-auto pb-4">
          <Composer />
        </div>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const ThreadWelcome: FC = () => {
  const isEmpty = useAuiState((s) => s.thread.isEmpty);
  if (!isEmpty) return null;

  return (
    <div className="mx-auto my-auto flex w-full max-w-2xl grow flex-col justify-center px-2">
      <h1 className="text-2xl font-semibold text-stone-50">今日はどう組む？</h1>
      <p className="mt-2 text-lg leading-8 text-stone-400">
        時間帯つきで予定を整理するよ。必要なら 5 分刻みまで詰められる。
      </p>
    </div>
  );
};

const ThreadMessage: FC = () => {
  const role = useAuiState((s) => s.message.role);

  return (
    <MessagePrimitive.Root className="mx-auto w-full max-w-2xl py-3" data-role={role}>
      {role === "user" ? <UserMessage /> : <AssistantMessage />}
    </MessagePrimitive.Root>
  );
};

const AssistantMessage: FC = () => {
  return (
    <div className="rounded-[24px] rounded-bl-md bg-white/10 px-4 py-3 text-sm leading-7 text-stone-100 shadow-[0_20px_45px_-35px_rgba(0,0,0,0.9)]">
      <MessagePrimitive.Parts>
        {({ part }) => {
          if (part.type === "text") return <MarkdownText />;
          return null;
        }}
      </MessagePrimitive.Parts>
    </div>
  );
};

const UserMessage: FC = () => {
  return (
    <div className="ml-auto max-w-[88%] rounded-[24px] rounded-br-md bg-[#f4a261] px-4 py-3 text-sm leading-7 text-stone-950">
      <MessagePrimitive.Parts />
    </div>
  );
};

const Composer: FC = () => {
  const isRunning = useAuiState((s) => s.thread.isRunning);

  return (
    <ComposerPrimitive.Root className="mx-auto w-full max-w-2xl">
      <div className="rounded-[28px] border border-white/12 bg-white/8 p-3 text-stone-50 shadow-[0_20px_45px_-35px_rgba(0,0,0,0.55)]">
        <ComposerPrimitive.Input
          placeholder="明日の午後を少し詰めたい、みたいに話しかけてね"
          className="min-h-10 w-full resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-stone-400"
          rows={1}
          aria-label="Message input"
        />
        <div className="mt-3 flex items-center justify-between">
          <p className="text-xs text-stone-400">候補を出してからタイムラインで微調整</p>
          {isRunning ? (
            <ComposerPrimitive.Cancel className="inline-flex size-10 items-center justify-center rounded-full bg-[#e76f51] text-white transition hover:bg-[#d95f42]">
              <SquareIcon className="size-4 fill-current" />
            </ComposerPrimitive.Cancel>
          ) : (
            <ComposerPrimitive.Send className="inline-flex size-10 items-center justify-center rounded-full bg-[#e76f51] text-white transition hover:bg-[#d95f42]">
              <ArrowUpIcon className="size-4" />
            </ComposerPrimitive.Send>
          )}
        </div>
      </div>
    </ComposerPrimitive.Root>
  );
};
