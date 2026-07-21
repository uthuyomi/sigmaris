"use client";

// 役割: Sigmaris Live を /chat の右サイドバーとして表示する、データソースを
// 知らない純粋な表示コンポーネント(デザイン統一・Live サイドバー デザイン
// 全面修正、docs/sigmaris/frontend_design_unification_report.md)。
//
// 【この版の設計方針(狭幅前提での組み直し・判断根拠)】
// 第五段階の初版は、/live(フルスクリーン)用の葉コンポーネント
// (LiveProcessFlow/LiveMetrics/LiveEventLog)を、そのまま幅だけ狭めて
// 縦積みしていた。その結果、メトリクスが「カードがびっしり並ぶ」ダッシュ
// ボード的な見た目になり、長いラベルが不自然に折り返されて読みにくかった。
// 本版では、サイドバー(実装上の幅 ≒ 400px)を前提に、UI を「カード」から
// 「連続したリスト/テキストの流れ」へ根本的に組み直す:
//   - メトリクス: カード群を廃止し、1行1指標の簡潔なリストに。ラベルは
//     「意図分類・直近の所要時間」→「意図分類」のように短縮。狭幅に全情報を
//     詰め込まず、直近所要時間+平均+ツール実行の要約に絞る。
//   - 処理の流れ: 横並びのカードから、縦並びの簡潔なリスト(点+ラベル+状態)へ。
//   - ログ: 罫線の濃いテーブルから、区切り線の薄い縦リストへ(時刻・処理名・
//     結果を積み、クリックで詳細を展開)。
//
// 【/live を変更しないための判断】
// 葉コンポーネント(LiveProcessFlow/LiveMetrics/LiveEventLog)・
// live-event-detail-panel は /live(LiveDashboard)が使うため一切変更しない。
// 本パネルは、それらの表示ではなく、共有の"計算ロジック"(computeStepStates/
// computeStepMetrics/computeToolCallMetrics/PROCESS_STEPS)と詳細パネル
// (LiveEventDetailPanel)だけを再利用し、サイドバー専用の list/text-flow を
// 独自に描画する。ログの処理名ラベル整形は、PROCESS_STEPS から導出する
// 小さなヘルパを本ファイル内に持つ(葉コンポーネント側の未export な整形関数を
// 共有するために /live 用ファイルへ手を入れることを避けるための、意図的な
// 局所化——判断根拠、報告書に記載)。
//
// 【/chat の常時ダーク保護との整合】
// 配色は /chat 左サイドバーと同じダーク基調(bg-[#171717])。ChatWorkspace の
// .dark サブツリー内に描画されるため、light テーマでもダークのまま。

import { CheckIcon, LoaderCircleIcon, XIcon } from "lucide-react";
import { Fragment, useState } from "react";
import {
  detailLookupFor,
  LiveEventDetailPanel,
} from "./live-event-detail-panel";
import { computeStepMetrics, computeToolCallMetrics } from "./metrics";
import {
  computeStepStates,
  PROCESS_STEPS,
  type ProcessStepState,
} from "./process-steps";
import type { LiveConnectionStatus, LiveEvent } from "./types";
import { PARSE_ERROR_EVENT } from "./use-live-events";
import { cn } from "@/lib/utils";

// ─── 接続状態 ────────────────────────────────────────────────────────
const STATUS_LABEL: Record<LiveConnectionStatus, string> = {
  connecting: "接続試行中...",
  open: "接続中",
  error: "エラー",
};
const STATUS_COLOR: Record<LiveConnectionStatus, string> = {
  connecting: "text-[#8e8ea0]",
  open: "text-emerald-400",
  error: "text-red-400",
};

// ─── ログの処理名整形(PROCESS_STEPS から導出。/live 用ファイルを触らない
//      ための局所ヘルパ) ─────────────────────────────────────────────
const STARTED_LABELS: Record<string, string> = {};
const FINISHED_LABELS: Record<string, string> = {};
for (const step of PROCESS_STEPS) {
  STARTED_LABELS[step.startedEvent] = `${step.label}・開始`;
  FINISHED_LABELS[step.finishedEvent] = `${step.label}・終了`;
}
const TOOL_CALL_LABELS: Record<string, string> = {
  tool_call_started: "ツール・開始",
  tool_call_finished: "ツール・終了",
};
const FINISHED_SUMMARIZERS: Record<string, (evt: LiveEvent) => string> = {};
for (const step of PROCESS_STEPS) {
  FINISHED_SUMMARIZERS[step.finishedEvent] = step.summarizeResult;
}

function logLabel(evt: LiveEvent): string {
  if (evt.event === PARSE_ERROR_EVENT) return "受信エラー";
  return (
    STARTED_LABELS[evt.event] ??
    FINISHED_LABELS[evt.event] ??
    TOOL_CALL_LABELS[evt.event] ??
    evt.event
  );
}

function toolCallSummary(evt: LiveEvent): string {
  const toolName = typeof evt.tool_name === "string" ? evt.tool_name : "unknown";
  if (evt.event === "tool_call_started") return `${toolName} を実行中...`;
  const ok = evt.ok === true;
  const elapsed = typeof evt.elapsed_ms === "number" ? ` ・ ${evt.elapsed_ms}ms` : "";
  return `${toolName}(${ok ? "成功" : "失敗"})${elapsed}`;
}

function logResult(evt: LiveEvent): string {
  if (evt.event === PARSE_ERROR_EVENT) return "配信データの解析に失敗しました";
  if (evt.event in STARTED_LABELS) return "実行中...";
  const summarize = FINISHED_SUMMARIZERS[evt.event];
  if (summarize) return summarize(evt);
  if (evt.event === "tool_call_started" || evt.event === "tool_call_finished") {
    return toolCallSummary(evt);
  }
  return "—";
}

// ─── 段階的な大きなテキスト(Redesign-1・主役) ───────────────────────
//
// メッセージ送信後の「今、何が起きているか」を、実データを埋め込んだ英語の
// 短い行として、大きく表示する。実際に発生したイベントを"順番に"見せている
// だけであり、演出的な遅延・疑似プログレスは一切足していない(Live-1「演出の
// 禁止」の原則を厳守)。段階が進むと、前の行が小さく薄くなり、最新の行が
// 主役(最下部・最大)になる——"覗いている"感覚を狙った構成。
//
// マスキング撤廃(バックエンド live_detail_masking.py)により、記憶検索の
// ヒット件数・ツール名等は実データがそのまま流れてくる(本人限定=/chatは
// JWT必須のため)。
function stageLine(evt: LiveEvent): string | null {
  const num = (v: unknown) => (typeof v === "number" ? v : null);
  const str = (v: unknown) => (typeof v === "string" ? v : null);
  switch (evt.event) {
    case "intent_classification_started":
      return "Classifying intent…";
    case "intent_classification_finished":
      return `Intent → ${str(evt.intent) ?? "unknown"}`;
    case "memory_search_started":
      return "Searching memory…";
    case "memory_search_finished": {
      const count = num(evt.result_count) ?? 0;
      return `Memory → ${count} hit${count === 1 ? "" : "s"}`;
    }
    case "response_generation_started":
      return "Generating response…";
    case "response_generation_finished": {
      const len = num(evt.response_length);
      return len !== null ? `Response → ${len} chars` : "Response ready";
    }
    case "tool_call_started":
      return `Running ${str(evt.tool_name) ?? "tool"}…`;
    case "tool_call_finished":
      return `${str(evt.tool_name) ?? "tool"} → ${evt.ok === true ? "done" : "failed"}`;
    default:
      return null; // 受信エラー・未知イベントは大きな表示には出さない
  }
}

function LiveStageDisplay({ events }: { events: LiveEvent[] }) {
  const lines: { key: string; text: string }[] = [];
  events.forEach((evt, idx) => {
    const text = stageLine(evt);
    if (text) lines.push({ key: `${evt.invocation_id}-${evt.event}-${idx}`, text });
  });
  const recent = lines.slice(-4); // 直近4段階のみ主役エリアに残す

  return (
    <div className="flex min-h-[7rem] flex-col justify-end gap-1.5 rounded-2xl border border-white/[0.06] bg-white/[0.02] px-4 py-5">
      {recent.length === 0 ? (
        <p className="font-mono text-sm text-[#5c5c66]">Waiting for activity…</p>
      ) : (
        recent.map((line, i) => {
          const fromBottom = recent.length - 1 - i; // 0 = 最新(主役)
          const cls =
            fromBottom === 0
              ? "text-xl font-semibold text-[#ececec]"
              : fromBottom === 1
                ? "text-base text-[#ececec]/60"
                : fromBottom === 2
                  ? "text-sm text-[#8e8ea0]/60"
                  : "text-xs text-[#8e8ea0]/35";
          return (
            <p
              key={line.key}
              className={cn(
                "font-mono leading-tight tracking-tight transition-all duration-300",
                cls,
              )}
            >
              {line.text}
            </p>
          );
        })
      )}
    </div>
  );
}

// ─── 小さなセクション見出し ──────────────────────────────────────────
function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#8e8ea0]">
      {children}
    </h3>
  );
}

// ─── 処理の流れ(縦リスト) ───────────────────────────────────────────
function StepDot({ status }: { status: ProcessStepState["status"] }) {
  if (status === "active") {
    return (
      <span className="relative flex size-6 shrink-0 items-center justify-center rounded-full bg-[#9b59b6] text-white">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-[#9b59b6] opacity-40" />
        <LoaderCircleIcon className="relative size-3 animate-spin" />
      </span>
    );
  }
  if (status === "done") {
    return (
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-emerald-400/40 bg-emerald-500/15 text-emerald-300">
        <CheckIcon className="size-3.5" />
      </span>
    );
  }
  return (
    <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-white/10 text-[10px] text-[#5c5c66]">
      •
    </span>
  );
}

function ProcessFlowList({ events }: { events: LiveEvent[] }) {
  const steps = computeStepStates(events, PROCESS_STEPS);
  return (
    <ul className="space-y-2.5">
      {steps.map((state) => {
        const statusText =
          state.status === "active" ? "実行中…" : state.status === "done" ? "完了" : "待機中";
        return (
          <li key={state.config.id} className="flex items-center gap-2.5">
            <StepDot status={state.status} />
            <span
              className={cn(
                "text-sm",
                state.status === "idle" ? "text-[#8e8ea0]" : "text-[#ececec]",
              )}
            >
              {state.config.label}
            </span>
            <span className="ml-auto shrink-0 text-xs text-[#8e8ea0]">{statusText}</span>
          </li>
        );
      })}
    </ul>
  );
}

// ─── メトリクス(1行1指標のリスト) ──────────────────────────────────
type MetricRow = { key: string; label: string; value: string; sub?: string };

function buildMetricRows(events: LiveEvent[]): MetricRow[] {
  const rows: MetricRow[] = [];
  for (const config of PROCESS_STEPS) {
    const m = computeStepMetrics(events, config);
    if (m.lastElapsedMs === null) continue; // データのある処理のみ(狭幅に全部詰め込まない)
    rows.push({
      key: config.id,
      label: config.label,
      value: `${m.lastElapsedMs}ms`,
      sub: m.averageElapsedMs !== null ? `平均 ${m.averageElapsedMs}ms・直近${m.sampleCount}件` : undefined,
    });
  }
  const tool = computeToolCallMetrics(events);
  if (tool.callCount > 0) {
    rows.push({
      key: "tool_call",
      label: "ツール実行",
      value: `${tool.callCount}件`,
      sub: `成功 ${tool.successCount}・失敗 ${tool.failureCount}`,
    });
  }
  return rows;
}

function MetricsList({ events }: { events: LiveEvent[] }) {
  const rows = buildMetricRows(events);
  if (rows.length === 0) {
    return (
      <p className="text-sm text-[#8e8ea0]">
        まだ計測データがありません。会話するとここに表示されます。
      </p>
    );
  }
  return (
    <dl className="space-y-2">
      {rows.map((row) => (
        <div key={row.key}>
          <div className="flex items-baseline justify-between gap-3">
            <dt className="text-sm text-[#ececec]">{row.label}</dt>
            <dd className="shrink-0 font-mono text-sm tabular-nums text-[#d8d8de]">{row.value}</dd>
          </div>
          {row.sub ? <p className="mt-0.5 text-xs text-[#8e8ea0]">{row.sub}</p> : null}
        </div>
      ))}
    </dl>
  );
}

// ─── ログ(区切り線の薄い縦リスト) ─────────────────────────────────
function LogList({ events }: { events: LiveEvent[] }) {
  const rows = [...events].reverse(); // 新しい順
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  if (rows.length === 0) {
    return (
      <p className="text-sm text-[#8e8ea0]">
        まだイベントを受信していません。/chatで会話すると表示されます。
      </p>
    );
  }

  return (
    <ul className="divide-y divide-white/[0.06]">
      {rows.map((evt, idx) => {
        const rowKey = `${evt.invocation_id}-${evt.event}-${idx}`;
        const detailable = detailLookupFor(evt) !== null;
        const isExpanded = expandedKey === rowKey;
        const time = new Date(evt.timestamp * 1000).toLocaleTimeString();
        return (
          <Fragment key={rowKey}>
            <li>
              <div
                className={cn(
                  "py-2",
                  detailable && "-mx-1 cursor-pointer rounded-lg px-1 hover:bg-white/[0.03]",
                )}
                onClick={detailable ? () => setExpandedKey(isExpanded ? null : rowKey) : undefined}
                role={detailable ? "button" : undefined}
                tabIndex={detailable ? 0 : undefined}
                onKeyDown={
                  detailable
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setExpandedKey(isExpanded ? null : rowKey);
                        }
                      }
                    : undefined
                }
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm text-[#ececec]">
                    {logLabel(evt)}
                    {detailable ? (
                      <span className="ml-1 text-xs text-[#8e8ea0]">{isExpanded ? "▲" : "▼"}</span>
                    ) : null}
                  </span>
                  <span className="shrink-0 font-mono text-[11px] text-[#8e8ea0]">{time}</span>
                </div>
                <p className="mt-0.5 break-words text-xs leading-5 text-[#8e8ea0]">
                  {logResult(evt)}
                </p>
              </div>
              {isExpanded ? (
                <div className="pb-2">
                  <LiveEventDetailPanel event={evt} />
                </div>
              ) : null}
            </li>
          </Fragment>
        );
      })}
    </ul>
  );
}

// ─── パネル本体 ──────────────────────────────────────────────────────
export function LiveSidebarPanel({
  events,
  status,
  onClose,
}: {
  events: LiveEvent[];
  status: LiveConnectionStatus;
  onClose?: () => void;
}) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-[#171717] text-[#ececec]">
      <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-white/10 px-3 pt-[env(safe-area-inset-top)]">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-[#9b59b6] text-sm font-semibold text-white">
            Σ
          </span>
          <span className="truncate text-sm font-semibold">Sigmaris Live</span>
          <span className={cn("shrink-0 text-xs", STATUS_COLOR[status])}>● {STATUS_LABEL[status]}</span>
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            aria-label="Liveパネルを閉じる"
            title="閉じる"
            className="flex size-9 shrink-0 items-center justify-center rounded-lg text-[#ececec] transition hover:bg-[#2f2f2f]"
          >
            <XIcon className="size-4" />
          </button>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto overscroll-contain px-4 py-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
        {/* 主役: 段階的な大きなテキスト(Redesign-1)。実イベントを順番に見せる。 */}
        <LiveStageDisplay events={events} />
        <p className="-mt-3 text-[11px] leading-5 text-[#5c5c66]">
          /chatでメッセージを送ると、その処理が上に大きく表示されます。以下は補助情報です。
        </p>

        <section>
          <SectionHeading>処理の流れ</SectionHeading>
          <ProcessFlowList events={events} />
        </section>

        <section>
          <SectionHeading>メトリクス</SectionHeading>
          <MetricsList events={events} />
        </section>

        <section>
          <SectionHeading>ログ（直近{events.length}件）</SectionHeading>
          <LogList events={events} />
        </section>
      </div>
    </aside>
  );
}
