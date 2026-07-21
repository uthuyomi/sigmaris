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

// ─── ログ(補助)を「1ターン単位・区分ごと・平易な言葉」で組み立てる
//      (Redesign-2)。既存イベントデータから導出するのみ・新規データ収集なし。
//      内部実装の専門用語(embedding/rerank/hybrid_score 等)は出さず、
//      「記憶: 12件ヒット」「文脈: しっかり参照」のような平易な表現へ変換する。
//      区分の並びは当初提案(Intent→Memory→Context→…→Tools→Generation)に
//      準拠。Model(モデルのティア)・Drive・Safety は既存イベントに対応する
//      データが無いため未実装(次段=Redesign-3へ申し送り、報告書参照)。

const _num = (v: unknown) => (typeof v === "number" ? v : null);
const _str = (v: unknown) => (typeof v === "string" ? v : null);

// 意図の内部コード → 平易な日本語(専門用語をそのまま出さない)。
const INTENT_LABELS: Record<string, string> = {
  general_chat: "雑談",
  event_lookup: "予定の確認",
  mobility_plan: "移動の計画",
  schedule_import: "予定の取り込み",
  calendar_write: "予定の登録",
  sync_control: "同期の操作",
};

// confidence_tier → 「記憶の選別・採用」の様子(内部語を出さず平易に)。
const TIER_ADOPTION: Record<string, string> = {
  confident: "しっかり参照",
  hedged: "控えめに参照",
  abstain: "参照なし(該当なし扱い)",
};

// model_tier(バックエンドが載せる実ティア) → 平易な日本語(Redesign-3)。
const MODEL_TIER_LABELS: Record<string, string> = {
  nano: "軽量モデル",
  standard: "標準モデル",
  advanced: "高度モデル",
};

// ツール名(chat_tool_definitions.py の function 名) → 平易な日本語(Redesign-4)。
// 内部の関数名をそのまま出さず、何をしたかが分かる表現にする(Redesign-2 の
// 平易化の原則の継続)。未知のツール名はそのまま表示(捏造しない)。
const TOOL_NAME_LABELS: Record<string, string> = {
  list_google_calendar_events: "カレンダー確認",
  create_google_calendar_events: "カレンダー登録",
  create_app_events: "予定の作成",
  delete_google_calendar_events: "カレンダー削除",
  delete_google_calendar_events_in_range: "カレンダー一括削除",
  read_google_sheet: "シート読み取り",
  search_app_events: "予定の検索",
  list_app_events: "予定の一覧",
  read_home_context: "自宅情報の参照",
  plan_google_route: "経路の計算",
  save_travel_plan_for_event: "移動予定の保存",
};

type CategoryRow = { key: string; label: string; value: string; detailEvent?: LiveEvent };

// 1ターン(同一 invocation_id)のイベント群から、区分ごとの平易な行を導出する。
function deriveTurnRows(events: LiveEvent[]): CategoryRow[] {
  const rows: CategoryRow[] = [];
  const has = (name: string) => events.some((e) => e.event === name);
  const find = (name: string) => events.find((e) => e.event === name);

  // Intent(意図)
  const intentEvt = find("intent_classification_finished");
  if (intentEvt) {
    const raw = _str(intentEvt.intent);
    const plain = raw ? (INTENT_LABELS[raw] ?? raw) : "判定済み";
    const src = intentEvt.source === "llm" ? "じっくり判定" : "即時判定";
    rows.push({ key: "intent", label: "意図", value: `${plain}(${src})` });
  } else if (has("intent_classification_started")) {
    rows.push({ key: "intent", label: "意図", value: "判定中…" });
  }

  // Model(応答生成に使ったモデルのティア、Redesign-3)。バックエンドが実値を
  // 載せる(model_tier: nano/standard/advanced)。専門的なモデル名ではなく
  // 平易なティア表現へ変換する。
  const genForModel = find("response_generation_finished");
  if (genForModel) {
    const tier = _str(genForModel.model_tier);
    const plain = tier ? (MODEL_TIER_LABELS[tier] ?? _str(genForModel.model) ?? tier) : null;
    if (plain) rows.push({ key: "model", label: "モデル", value: plain });
  }

  // Memory(記憶) ＋ Context(文脈: 選別・採用)
  const memEvt = find("memory_search_finished");
  if (memEvt) {
    const count = _num(memEvt.result_count) ?? 0;
    rows.push({ key: "memory", label: "記憶", value: `${count}件ヒット`, detailEvent: memEvt });
    const tier = _str(memEvt.confidence_tier);
    const adoption = tier ? (TIER_ADOPTION[tier] ?? tier) : null;
    if (adoption) {
      const decomposed = memEvt.was_decomposed === true ? "・複数の観点で検索" : "";
      rows.push({ key: "context", label: "文脈", value: `${adoption}${decomposed}` });
    }
  } else if (has("memory_search_started")) {
    rows.push({ key: "memory", label: "記憶", value: "検索中…" });
  }

  // Drive(内発的動機、Redesign-3): S-2(Goal Proposal)由来の自発的な行動の
  // ターンのみ表示する。通常の受動的な会話では is_proactive=false のため、
  // この行は出ない(該当なし)。現状 goal_proposal は未配線のため実質常に非表示
  // (backend 側コメント参照)。
  const memForDrive = find("memory_search_finished");
  if (memForDrive?.is_proactive === true) {
    rows.push({ key: "drive", label: "動機", value: "自発的な行動" });
  }

  // Safety(安全機構の痕跡、Redesign-3): 実際に安全機構が働いた場合のみ表示。
  // バックエンドが safety_check を emit するのは発火時だけ(呼び名の統一・
  // 事実整合ガードの検出)なので、何も働かなかった通常ターンでは行は出ない。
  const safetyEvt = find("safety_check");
  if (safetyEvt) {
    const parts: string[] = [];
    if (safetyEvt.name_replaced === true) parts.push("呼び名を統一");
    if (safetyEvt.fact_check_flagged === true) {
      const n = _num(safetyEvt.fact_check_violation_count) ?? 0;
      parts.push(`事実確認で要注意${n > 0 ? `(${n}件)` : ""}`);
    }
    if (parts.length > 0) rows.push({ key: "safety", label: "安全", value: parts.join("・") });
  }

  // Tools(ツール): 1ターンに0〜複数回。複数呼び出しは1件ずつ別の行として
  // 区別表示する(Redesign-4: 読みやすいツール名＋成否＋所要時間。クリックで
  // 引数の詳細を展開)。
  const toolsFinished = events.filter((e) => e.event === "tool_call_finished");
  toolsFinished.forEach((t, i) => {
    const raw = _str(t.tool_name);
    const tool = raw ? (TOOL_NAME_LABELS[raw] ?? raw) : "ツール";
    const ok = t.ok === true;
    const ms = _num(t.elapsed_ms);
    const elapsed = ms !== null ? `・${ms}ms` : "";
    rows.push({
      key: `tool-${i}`,
      label: "ツール",
      value: `${tool}(${ok ? "成功" : "失敗"})${elapsed}`,
      detailEvent: t,
    });
  });
  if (toolsFinished.length === 0 && has("tool_call_started")) {
    rows.push({ key: "tool-run", label: "ツール", value: "実行中…" });
  }

  // Generation(生成)
  const genEvt = find("response_generation_finished");
  if (genEvt) {
    const len = _num(genEvt.response_length);
    rows.push({ key: "gen", label: "生成", value: len !== null ? `${len}文字` : "完了" });
  } else if (has("response_generation_started")) {
    rows.push({ key: "gen", label: "生成", value: "生成中…" });
  }

  return rows;
}

type TurnGroup = { invocationId: string; time: number; events: LiveEvent[] };

// イベント配列を invocation_id(=1ターン)でグルーピングし、新しいターン順に返す。
function groupTurns(events: LiveEvent[]): TurnGroup[] {
  const map = new Map<string, LiveEvent[]>();
  for (const e of events) {
    if (!e.invocation_id) continue; // 受信エラー等・ターンに属さないものは除外
    const arr = map.get(e.invocation_id);
    if (arr) arr.push(e);
    else map.set(e.invocation_id, [e]);
  }
  const groups: TurnGroup[] = [];
  for (const [invocationId, evs] of map) {
    groups.push({ invocationId, time: Math.min(...evs.map((e) => e.timestamp)), events: evs });
  }
  groups.sort((a, b) => b.time - a.time); // 新しいターンを上に
  return groups.slice(0, 20); // 直近20ターン
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

// ─── ログ(1ターン単位・区分ごとの平易なリスト、Redesign-2) ──────────
function LiveTurnLog({ events }: { events: LiveEvent[] }) {
  const groups = groupTurns(events);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  if (groups.length === 0) {
    return (
      <p className="text-sm text-[#8e8ea0]">
        まだ会話がありません。/chatでメッセージを送ると、ターンごとに表示されます。
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {groups.map((group) => {
        const rows = deriveTurnRows(group.events);
        if (rows.length === 0) return null;
        const time = new Date(group.time * 1000).toLocaleTimeString();
        return (
          <div key={group.invocationId} className="border-l-2 border-white/10 pl-3">
            <p className="mb-1 font-mono text-[11px] text-[#5c5c66]">{time}</p>
            <ul className="space-y-0.5">
              {rows.map((row) => {
                const detailable = !!row.detailEvent && detailLookupFor(row.detailEvent) !== null;
                const rowKey = `${group.invocationId}-${row.key}`;
                const isExpanded = expandedKey === rowKey;
                return (
                  <Fragment key={rowKey}>
                    <li>
                      <div
                        className={cn(
                          "flex items-baseline gap-2 py-0.5",
                          detailable && "-mx-1 cursor-pointer rounded px-1 hover:bg-white/[0.03]",
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
                        <span className="w-9 shrink-0 text-xs text-[#8e8ea0]">{row.label}</span>
                        <span className="min-w-0 flex-1 break-words text-sm text-[#ececec]">
                          {row.value}
                          {detailable ? (
                            <span className="ml-1 text-xs text-[#8e8ea0]">{isExpanded ? "▲" : "▼"}</span>
                          ) : null}
                        </span>
                      </div>
                      {isExpanded && row.detailEvent ? (
                        <div className="py-1">
                          <LiveEventDetailPanel event={row.detailEvent} />
                        </div>
                      ) : null}
                    </li>
                  </Fragment>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

// ─── 折りたたみ可能なセクション(Redesign-4) ────────────────────────
// 「一時停止しても情報量が豊富」を狙いつつ、狭幅で崩れないよう、二次的な
// 情報(数値メトリクス等)は既定で畳んでおき、必要な人だけ展開できるように
// する(依頼書「常に全て開いた状態にする必要はない」)。主役(段階表示)・
// 処理の流れ・ターンごとのログ(＝メモリ/文脈/モデル/Drive/Safety/ツールの
// 一望＝このターンのTimeline)は常時表示のまま。
function CollapsibleSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="mb-2 flex w-full items-center justify-between text-xs font-semibold uppercase tracking-wider text-[#8e8ea0] transition hover:text-[#ececec]"
      >
        <span>{title}</span>
        <span className="text-[10px]">{open ? "▲" : "▼"}</span>
      </button>
      {open ? children : null}
    </section>
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

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-4 py-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
        {/* 主役: 段階的な大きなテキスト(Redesign-1)。実イベントを順番に見せる。 */}
        <LiveStageDisplay events={events} />
        <p className="-mt-2.5 text-[11px] leading-5 text-[#5c5c66]">
          /chatでメッセージを送ると、その処理が上に大きく表示されます。以下は各処理の内訳です。
        </p>

        {/* 常時表示(一時停止しても読める中核): 処理の流れ ＋ ターンごとの内訳
            (メモリ/文脈/モデル/Drive/Safety/ツール＝このターンのTimeline)。 */}
        <section>
          <SectionHeading>処理の流れ</SectionHeading>
          <ProcessFlowList events={events} />
        </section>

        <section>
          <SectionHeading>ログ（ターンごと）</SectionHeading>
          <LiveTurnLog events={events} />
        </section>

        {/* 二次情報: 数値メトリクスは既定で畳む(展開で所要時間等を確認)。 */}
        <CollapsibleSection title="メトリクス（所要時間）">
          <MetricsList events={events} />
        </CollapsibleSection>
      </div>
    </aside>
  );
}
