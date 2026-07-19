// 役割: Sigmaris Live-3/他の処理への拡大(docs/sigmaris/
// sigmaris_live_report.md)。「簡単なメトリクス」(依頼書2章3節)を、
// 既存のイベントデータのみから算出する純粋関数。新しいデータ収集は
// 一切行わない——各finishedイベントが既に持つelapsed_ms等のフィールド
// (Live-2/他の処理への拡大タスクで実装済み)を集計するのみ。

import type { ProcessStepConfig } from "./process-steps";
import type { LiveEvent } from "./types";

export type StepMetrics = {
  /** 直近1件のelapsed_ms。まだ1件も無い場合null。 */
  lastElapsedMs: number | null;
  /** 直近sampleSize件の平均elapsed_ms。 */
  averageElapsedMs: number | null;
  /** 平均の算出に使った実際のサンプル数(sampleSizeに満たない場合もある)。 */
  sampleCount: number;
  /** ヒューリスティックで即座に判定できた件数(直近sampleSize件中)。 */
  heuristicCount: number;
  /** LLM呼び出しにフォールバックした件数(同上)。 */
  llmCount: number;
};

const DEFAULT_SAMPLE_SIZE = 20;

export function computeStepMetrics(
  events: readonly LiveEvent[],
  config: ProcessStepConfig,
  sampleSize: number = DEFAULT_SAMPLE_SIZE,
): StepMetrics {
  const finished = events.filter((evt) => evt.event === config.finishedEvent);
  const recent = finished.slice(-sampleSize);

  const elapsedValues = recent
    .map((evt) => (typeof evt.elapsed_ms === "number" ? evt.elapsed_ms : null))
    .filter((value): value is number => value !== null);

  const lastElapsedMs = elapsedValues.length > 0 ? elapsedValues[elapsedValues.length - 1] : null;
  const averageElapsedMs =
    elapsedValues.length > 0
      ? Math.round(elapsedValues.reduce((sum, value) => sum + value, 0) / elapsedValues.length)
      : null;

  const heuristicCount = recent.filter((evt) => evt.source === "heuristic").length;
  const llmCount = recent.filter((evt) => evt.source === "llm").length;

  return {
    lastElapsedMs,
    averageElapsedMs,
    sampleCount: recent.length,
    heuristicCount,
    llmCount,
  };
}

export type ToolCallMetrics = {
  callCount: number;
  successCount: number;
  failureCount: number;
};

/** tool_callは、process-steps.tsのPROCESS_STEPSに含めていない(1ターンに
 * 0〜複数回発生しうるため、他の処理と粒度が異なる——process-steps.tsの
 * モジュールdocstring参照)。そのため、この専用関数だけがtool_call_
 * finishedイベントを直接見る、唯一の場所になっている。 */
export function computeToolCallMetrics(events: readonly LiveEvent[], sampleSize: number = DEFAULT_SAMPLE_SIZE): ToolCallMetrics {
  const finished = events.filter((evt) => evt.event === "tool_call_finished");
  const recent = finished.slice(-sampleSize);
  const successCount = recent.filter((evt) => evt.ok === true).length;
  return {
    callCount: recent.length,
    successCount,
    failureCount: recent.length - successCount,
  };
}
