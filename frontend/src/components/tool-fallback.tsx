"use client";
// 役割: assistant-uiのツール実行結果が未対応の場合の代替表示を行う。


import { memo, useCallback, useRef, useState } from "react";
import {
  AlertCircleIcon,
  CalendarCheck2Icon,
  CalendarDaysIcon,
  CheckIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  LoaderIcon,
  XCircleIcon,
} from "lucide-react";
import {
  useScrollLock,
  type ToolCallMessagePartStatus,
  type ToolCallMessagePartComponent,
} from "@assistant-ui/react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui";
import { cn } from "@/lib/utils";

const ANIMATION_DURATION = 200;

export type ToolFallbackRootProps = Omit<
  React.ComponentProps<typeof Collapsible>,
  "open" | "onOpenChange"
> & {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  defaultOpen?: boolean;
};

function ToolFallbackRoot({
  className,
  open: controlledOpen,
  onOpenChange: controlledOnOpenChange,
  defaultOpen = false,
  children,
  ...props
}: ToolFallbackRootProps) {
  const collapsibleRef = useRef<HTMLDivElement>(null);
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const lockScroll = useScrollLock(collapsibleRef, ANIMATION_DURATION);

  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;

  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (!open) {
        lockScroll();
      }
      if (!isControlled) {
        setUncontrolledOpen(open);
      }
      controlledOnOpenChange?.(open);
    },
    [lockScroll, isControlled, controlledOnOpenChange],
  );

  return (
    <Collapsible
      ref={collapsibleRef}
      data-slot="tool-fallback-root"
      open={isOpen}
      onOpenChange={handleOpenChange}
      className={cn(
        "aui-tool-fallback-root group/tool-fallback-root w-full rounded-lg border py-3",
        className,
      )}
      style={
        {
          "--animation-duration": `${ANIMATION_DURATION}ms`,
        } as React.CSSProperties
      }
      {...props}
    >
      {children}
    </Collapsible>
  );
}

type ToolStatus = ToolCallMessagePartStatus["type"];

const statusIconMap: Record<ToolStatus, React.ElementType> = {
  running: LoaderIcon,
  complete: CheckIcon,
  incomplete: XCircleIcon,
  "requires-action": AlertCircleIcon,
};

type ToolResultRecord = Record<string, unknown>;

type CalendarEventSummary = {
  title: string;
  startsAt?: string;
  endsAt?: string;
  location?: string;
};

const registrationTools = new Set([
  "create_google_calendar_events",
  "create_app_events",
  "save_travel_plan_for_event",
]);

const calendarLookupTools = new Set([
  "list_app_events",
  "search_app_events",
  "list_google_calendar_events",
]);

const parseResultRecord = (result: unknown): ToolResultRecord | null => {
  if (!result) return null;
  if (typeof result === "object" && !Array.isArray(result)) {
    return result as ToolResultRecord;
  }
  if (typeof result !== "string") return null;

  try {
    const parsed = JSON.parse(result);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as ToolResultRecord)
      : null;
  } catch {
    return null;
  }
};

const readString = (value: unknown) => (typeof value === "string" ? value : undefined);

const readEventSummary = (event: unknown): CalendarEventSummary | null => {
  if (!event || typeof event !== "object" || Array.isArray(event)) return null;
  const item = event as ToolResultRecord;
  const start = item.start as ToolResultRecord | undefined;
  const end = item.end as ToolResultRecord | undefined;
  const title =
    readString(item.title) ??
    readString(item.summary) ??
    readString(item.name) ??
    "無題の予定";

  return {
    title,
    startsAt:
      readString(item.starts_at) ??
      readString(item.start) ??
      readString(start?.dateTime) ??
      readString(start?.date),
    endsAt:
      readString(item.ends_at) ??
      readString(item.end) ??
      readString(end?.dateTime) ??
      readString(end?.date),
    location: readString(item.location_text) ?? readString(item.location),
  };
};

const readEventSummaries = (result: ToolResultRecord) => {
  const eventSources = [
    result.createdAppEvents,
    result.createdGoogleEvents,
    result.created,
    result.createdEvent ? [result.createdEvent] : undefined,
    result.events,
  ];

  for (const source of eventSources) {
    if (!Array.isArray(source)) continue;
    return source
      .map(readEventSummary)
      .filter((event): event is CalendarEventSummary => Boolean(event));
  }

  return [];
};

const formatDateTime = (value?: string) => {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("ja-JP", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

const formatEventTimeRange = (event: CalendarEventSummary) => {
  const start = formatDateTime(event.startsAt);
  const end = formatDateTime(event.endsAt);
  if (start && end) return `${start} - ${end}`;
  return start ?? end ?? null;
};

const getErrorText = (
  result: ToolResultRecord | null,
  status?: ToolCallMessagePartStatus,
) => {
  if (status?.type === "incomplete") {
    if (typeof status.error === "string") return status.error;
    if (status.error) return JSON.stringify(status.error);
    if (status.reason === "cancelled") return "実行が停止されました。";
  }

  if (!result) return null;
  return (
    readString(result.reason) ??
    readString(result.error) ??
    readString(result.status) ??
    null
  );
};

function ToolResultCard({
  tone,
  icon,
  title,
  description,
  children,
}: {
  tone: "success" | "info" | "error" | "running";
  icon: React.ReactNode;
  title: string;
  description?: string | null;
  children?: React.ReactNode;
}) {
  const toneClass = {
    success: "border-emerald-400/25 bg-emerald-400/10 text-emerald-50",
    info: "border-white/10 bg-[#2f2f2f] text-[#ececec]",
    error: "border-red-400/30 bg-red-500/10 text-red-50",
    running: "border-white/10 bg-[#2f2f2f] text-[#ececec]",
  }[tone];
  const iconClass = {
    success: "bg-emerald-400 text-[#102017]",
    info: "bg-[#9b59b6] text-white",
    error: "bg-red-400 text-[#2b0b0b]",
    running: "bg-[#9b59b6] text-white",
  }[tone];

  return (
    <div className={cn("mt-3 max-w-xl rounded-2xl border px-4 py-3 shadow-[0_18px_45px_-34px_rgba(0,0,0,0.8)]", toneClass)}>
      <div className="flex gap-3">
        <div className={cn("mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full", iconClass)}>
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold leading-6">{title}</div>
          {description ? (
            <p className="mt-0.5 text-xs leading-5 text-[#c9c9d1]">
              {description}
            </p>
          ) : null}
          {children}
        </div>
      </div>
    </div>
  );
}

function CalendarEventList({ events }: { events: CalendarEventSummary[] }) {
  if (!events.length) return null;

  return (
    <div className="mt-3 space-y-2">
      {events.slice(0, 5).map((event, index) => {
        const timeRange = formatEventTimeRange(event);
        return (
          <div
            key={`${event.title}-${event.startsAt ?? index}`}
            className="rounded-xl border border-white/10 bg-black/10 px-3 py-2"
          >
            <div className="truncate text-sm font-medium">{event.title}</div>
            {timeRange ? (
              <div className="mt-0.5 text-xs leading-5 text-[#c9c9d1]">
                {timeRange}
              </div>
            ) : null}
            {event.location ? (
              <div className="truncate text-xs leading-5 text-[#8e8ea0]">
                {event.location}
              </div>
            ) : null}
          </div>
        );
      })}
      {events.length > 5 ? (
        <div className="px-1 text-xs text-[#8e8ea0]">
          ほか {events.length - 5} 件
        </div>
      ) : null}
    </div>
  );
}

function SpecializedToolCard({
  toolName,
  result,
  status,
}: {
  toolName: string;
  result?: unknown;
  status?: ToolCallMessagePartStatus;
}) {
  const resultRecord = parseResultRecord(result);
  const isRunning = status?.type === "running";
  const errorText =
    resultRecord?.ok === false || status?.type === "incomplete"
      ? getErrorText(resultRecord, status)
      : null;

  if (isRunning) {
    return (
      <ToolResultCard
        tone="running"
        icon={<LoaderIcon className="size-4 animate-spin" />}
        title="ツールを実行中"
        description="シグマリスが予定情報を確認しています。"
      />
    );
  }

  if (errorText) {
    return (
      <ToolResultCard
        tone="error"
        icon={<CircleAlertIcon className="size-4" />}
        title="実行できませんでした"
        description={errorText}
      />
    );
  }

  if (!resultRecord) return null;

  if (
    registrationTools.has(toolName) &&
    resultRecord.ok === true &&
    resultRecord.registrationStatus === "registered"
  ) {
    const events = readEventSummaries(resultRecord);
    const count =
      typeof resultRecord.appCreatedCount === "number"
        ? resultRecord.appCreatedCount
        : typeof resultRecord.createdCount === "number"
          ? resultRecord.createdCount
          : events.length;

    return (
      <ToolResultCard
        tone="success"
        icon={<CalendarCheck2Icon className="size-4" />}
        title="予定を登録しました"
        description={`${count || 1}件の予定を保存しました。`}
      >
        <CalendarEventList events={events} />
      </ToolResultCard>
    );
  }

  if (calendarLookupTools.has(toolName) && resultRecord.ok === true) {
    const events = readEventSummaries(resultRecord);
    const count =
      typeof resultRecord.count === "number" ? resultRecord.count : events.length;

    return (
      <ToolResultCard
        tone="info"
        icon={<CalendarDaysIcon className="size-4" />}
        title="カレンダーを確認しました"
        description={`${count}件の予定が見つかりました。`}
      >
        <CalendarEventList events={events} />
      </ToolResultCard>
    );
  }

  return null;
}

function ToolFallbackTrigger({
  toolName,
  status,
  className,
  ...props
}: React.ComponentProps<typeof CollapsibleTrigger> & {
  toolName: string;
  status?: ToolCallMessagePartStatus;
}) {
  const statusType = status?.type ?? "complete";
  const isRunning = statusType === "running";
  const isCancelled =
    status?.type === "incomplete" && status.reason === "cancelled";

  const Icon = statusIconMap[statusType];
  const label = isCancelled ? "Cancelled tool" : "Used tool";

  return (
    <CollapsibleTrigger
      data-slot="tool-fallback-trigger"
      className={cn(
        "aui-tool-fallback-trigger group/trigger flex w-full items-center gap-2 px-4 text-sm transition-colors",
        className,
      )}
      {...props}
    >
      <Icon
        data-slot="tool-fallback-trigger-icon"
        className={cn(
          "aui-tool-fallback-trigger-icon size-4 shrink-0",
          isCancelled && "text-muted-foreground",
          isRunning && "animate-spin",
        )}
      />
      <span
        data-slot="tool-fallback-trigger-label"
        className={cn(
          "aui-tool-fallback-trigger-label-wrapper relative inline-block grow text-left leading-none",
          isCancelled && "text-muted-foreground line-through",
        )}
      >
        <span>
          {label}: <b>{toolName}</b>
        </span>
        {isRunning && (
          <span
            aria-hidden
            data-slot="tool-fallback-trigger-shimmer"
            className="aui-tool-fallback-trigger-shimmer shimmer pointer-events-none absolute inset-0 motion-reduce:animate-none"
          >
            {label}: <b>{toolName}</b>
          </span>
        )}
      </span>
      <ChevronDownIcon
        data-slot="tool-fallback-trigger-chevron"
        className={cn(
          "aui-tool-fallback-trigger-chevron size-4 shrink-0",
          "transition-transform duration-(--animation-duration) ease-out",
          "group-data-[state=closed]/trigger:-rotate-90",
          "group-data-[state=open]/trigger:rotate-0",
        )}
      />
    </CollapsibleTrigger>
  );
}

function ToolFallbackContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof CollapsibleContent>) {
  return (
    <CollapsibleContent
      data-slot="tool-fallback-content"
      className={cn(
        "aui-tool-fallback-content relative overflow-hidden text-sm outline-none",
        "group/collapsible-content ease-out",
        "data-[state=closed]:animate-collapsible-up",
        "data-[state=open]:animate-collapsible-down",
        "data-[state=closed]:fill-mode-forwards",
        "data-[state=closed]:pointer-events-none",
        "data-[state=open]:duration-(--animation-duration)",
        "data-[state=closed]:duration-(--animation-duration)",
        className,
      )}
      {...props}
    >
      <div className="mt-3 flex flex-col gap-2 border-t pt-2">{children}</div>
    </CollapsibleContent>
  );
}

function ToolFallbackArgs({
  argsText,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  argsText?: string;
}) {
  if (!argsText) return null;

  return (
    <div
      data-slot="tool-fallback-args"
      className={cn("aui-tool-fallback-args px-4", className)}
      {...props}
    >
      <pre className="aui-tool-fallback-args-value whitespace-pre-wrap">
        {argsText}
      </pre>
    </div>
  );
}

function ToolFallbackResult({
  result,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  result?: unknown;
}) {
  if (result === undefined) return null;

  return (
    <div
      data-slot="tool-fallback-result"
      className={cn(
        "aui-tool-fallback-result border-t border-dashed px-4 pt-2",
        className,
      )}
      {...props}
    >
      <p className="aui-tool-fallback-result-header font-semibold">Result:</p>
      <pre className="aui-tool-fallback-result-content whitespace-pre-wrap">
        {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
      </pre>
    </div>
  );
}

function ToolFallbackError({
  status,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  status?: ToolCallMessagePartStatus;
}) {
  if (status?.type !== "incomplete") return null;

  const error = status.error;
  const errorText = error
    ? typeof error === "string"
      ? error
      : JSON.stringify(error)
    : null;

  if (!errorText) return null;

  const isCancelled = status.reason === "cancelled";
  const headerText = isCancelled ? "Cancelled reason:" : "Error:";

  return (
    <div
      data-slot="tool-fallback-error"
      className={cn("aui-tool-fallback-error px-4", className)}
      {...props}
    >
      <p className="aui-tool-fallback-error-header font-semibold text-muted-foreground">
        {headerText}
      </p>
      <p className="aui-tool-fallback-error-reason text-muted-foreground">
        {errorText}
      </p>
    </div>
  );
}

const ToolFallbackImpl: ToolCallMessagePartComponent = ({
  toolName,
  argsText,
  result,
  status,
}) => {
  const isCancelled =
    status?.type === "incomplete" && status.reason === "cancelled";
  const specializedCard = SpecializedToolCard({ toolName, result, status });
  if (specializedCard) {
    return specializedCard;
  }

  return (
    <ToolFallbackRoot
      className={cn(isCancelled && "border-muted-foreground/30 bg-muted/30")}
    >
      <ToolFallbackTrigger toolName={toolName} status={status} />
      <ToolFallbackContent>
        <ToolFallbackError status={status} />
        <ToolFallbackArgs
          argsText={argsText}
          className={cn(isCancelled && "opacity-60")}
        />
        {!isCancelled && <ToolFallbackResult result={result} />}
      </ToolFallbackContent>
    </ToolFallbackRoot>
  );
};

const ToolFallback = memo(
  ToolFallbackImpl,
) as unknown as ToolCallMessagePartComponent & {
  Root: typeof ToolFallbackRoot;
  Trigger: typeof ToolFallbackTrigger;
  Content: typeof ToolFallbackContent;
  Args: typeof ToolFallbackArgs;
  Result: typeof ToolFallbackResult;
  Error: typeof ToolFallbackError;
};

ToolFallback.displayName = "ToolFallback";
ToolFallback.Root = ToolFallbackRoot;
ToolFallback.Trigger = ToolFallbackTrigger;
ToolFallback.Content = ToolFallbackContent;
ToolFallback.Args = ToolFallbackArgs;
ToolFallback.Result = ToolFallbackResult;
ToolFallback.Error = ToolFallbackError;

export {
  ToolFallback,
  ToolFallbackRoot,
  ToolFallbackTrigger,
  ToolFallbackContent,
  ToolFallbackArgs,
  ToolFallbackResult,
  ToolFallbackError,
};
