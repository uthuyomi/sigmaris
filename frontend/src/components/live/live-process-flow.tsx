"use client";

// 役割: Sigmaris Live-3(docs/sigmaris/sigmaris_live_report.md)。
// 「処理の流れ」の視覚化(依頼書1章)。PROCESS_STEPS(process-steps.ts)を
// 走査するだけの、データソースを知らない純粋な表示コンポーネント。
//
// 【「本物のリアルタイム性」と「演出」の境界線(依頼書の重要な制約)】
// activeの間は、実際に`_started`イベントを受信してから`_finished`
// イベントを受信するまでの、実時間だけスピナーを表示する——一定時間で
// 100%に到達するような疑似プログレスバーは実装していない(classify_
// chat_intent()は「候補を絞り込んでいく」ような段階的処理ではなく、
// Live-1、5.2節が確認した通り一括で完了するバッチ処理であるため、
// 段階的な進捗という演出の材料がそもそも存在しない)。doneになった
// 瞬間、要約結果を一度に表示する。

import { CheckIcon, LoaderCircleIcon } from "lucide-react";
import { computeStepStates, PROCESS_STEPS, type ProcessStepState } from "./process-steps";
import type { LiveEvent } from "./types";

function StepDot({ status }: { status: ProcessStepState["status"] }) {
  if (status === "active") {
    return (
      <span className="relative flex size-8 shrink-0 items-center justify-center rounded-full bg-[#9b59b6] text-white">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-[#9b59b6] opacity-40" />
        <LoaderCircleIcon className="relative size-4 animate-spin" />
      </span>
    );
  }
  if (status === "done") {
    return (
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-emerald-400/40 bg-emerald-500/15 text-emerald-300">
        <CheckIcon className="size-4" />
      </span>
    );
  }
  return (
    <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/[0.03] text-[#5c5c66]">
      •
    </span>
  );
}

function resultSummary(state: ProcessStepState): string | null {
  const evt = state.lastFinishedEvent;
  if (!evt) return null;
  // 意図分類固有のフィールド(intent/source/needs_search)を要約する。
  // 将来processが増えた場合は、ここにconfig.id別の分岐を追加する
  // (現時点ではintent_classificationのみのため、汎用化はまだ行っていない
  // ——1件のために抽象化を先取りしないという判断、報告書に明記)。
  if (state.config.id === "intent_classification") {
    const intent = typeof evt.intent === "string" ? evt.intent : "unknown";
    const source = evt.source === "llm" ? "LLM判定" : "即時判定";
    const needsSearch = evt.needs_search ? "・検索要" : "";
    const elapsed = typeof evt.elapsed_ms === "number" ? `${evt.elapsed_ms}ms` : null;
    return `${intent}(${source}${needsSearch})${elapsed ? ` ・ ${elapsed}` : ""}`;
  }
  return "完了";
}

export function LiveProcessFlow({ events }: { events: LiveEvent[] }) {
  const steps = computeStepStates(events, PROCESS_STEPS);

  return (
    <div className="rounded-3xl border border-white/10 bg-[#2a2a2a] p-4 shadow-[0_18px_60px_-45px_rgba(0,0,0,0.75)] sm:p-5">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-[#ececec] sm:text-lg">処理の流れ</h2>
        <p className="mt-1 text-sm leading-6 text-[#8e8ea0]">
          今、シグマリスの内部でどの処理が動いているかを表示します。現時点では意図分類のみが対象です(今後、記憶検索等が追加される予定です)。
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {steps.map((state, index) => (
          <div key={state.config.id} className="flex items-center gap-3">
            {index > 0 ? <span aria-hidden className="h-px w-6 bg-white/10" /> : null}
            <div className="flex min-w-0 items-center gap-3 rounded-2xl border border-white/10 bg-[#212121] px-4 py-3">
              <StepDot status={state.status} />
              <div className="min-w-0">
                <p className="text-sm font-medium text-[#ececec]">{state.config.label}</p>
                <p className="truncate text-xs text-[#8e8ea0]">
                  {state.status === "active"
                    ? "実行中..."
                    : state.status === "done"
                      ? (resultSummary(state) ?? "完了")
                      : "待機中"}
                </p>
              </div>
            </div>
          </div>
        ))}
        {/* 将来の処理(記憶検索・Evidence検索・応答生成等)は、
            PROCESS_STEPS(process-steps.ts)へ1エントリ追加するだけで、
            この横並びのフローに自然に追加される。 */}
      </div>
    </div>
  );
}
