// 役割: Sigmaris Live-3(docs/sigmaris/sigmaris_live_report.md)。「簡単な
// メトリクス」(依頼書2章3節)を、既存のイベントデータのみから算出する
// 純粋関数。新しいデータ収集は一切行わない——intent_classification_
// finishedイベントが既に持つelapsed_ms/sourceフィールド(Live-2で実装
// 済み)を集計するのみ。

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
