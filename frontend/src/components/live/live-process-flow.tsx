"use client";

// 役割: Sigmaris Live-3/他の処理への拡大(docs/sigmaris/
// sigmaris_live_report.md)。「処理の流れ」の視覚化(依頼書1章)。
// PROCESS_STEPS(process-steps.ts)を走査するだけの、データソースを
// 知らない純粋な表示コンポーネント。
//
// 【「本物のリアルタイム性」と「演出」の境界線(依頼書の重要な制約)】
// activeの間は、実際に`_started`イベントを受信してから`_finished`
// イベントを受信するまでの、実時間だけスピナーを表示する——一定時間で
// 100%に到達するような疑似プログレスバーは実装していない。記憶検索は
// Live-1、5.2節が確認した通り一括で完了するバッチ処理であるため、
// 段階的な進捗という演出の材料がそもそも存在しない。応答生成は逆に
// 本物のstreamingであるが、Live-1、4.2節のプライバシー方針により応答
// 本文自体はイベントに含めていないため、doneになるまでの実時間の長さ
// そのものが「本物のリアルタイム性」の表現になる(判断根拠、報告書に
// 詳述)。doneになった瞬間、要約結果を一度に表示する。
//
// 【他の処理への拡大タスクでの改良(要件5への対応)】
// 各ステップの結果要約は、config.summarizeResult()(process-steps.ts)を
// 呼ぶだけになった——本コンポーネントには、特定の処理名やイベント
// フィールドへの言及が一切無い。新しい処理を追加する際、このファイルは
// 一切変更する必要がない。

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
  if (!state.lastFinishedEvent) return null;
  return state.config.summarizeResult(state.lastFinishedEvent);
}

export function LiveProcessFlow({ events }: { events: LiveEvent[] }) {
  const steps = computeStepStates(events, PROCESS_STEPS);

  return (
    <div className="rounded-3xl border border-white/10 bg-[#2a2a2a] p-4 shadow-[0_18px_60px_-45px_rgba(0,0,0,0.75)] sm:p-5">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-[#ececec] sm:text-lg">処理の流れ</h2>
        <p className="mt-1 text-sm leading-6 text-[#8e8ea0]">
          今、シグマリスの内部でどの処理が動いているかを表示します(意図分類・記憶検索・応答生成)。
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
        {/* 将来の処理(Evidence検索等)は、PROCESS_STEPS(process-steps.ts)
            へ1エントリ追加するだけで、この横並びのフローに自然に追加
            される。 */}
      </div>
    </div>
  );
}
