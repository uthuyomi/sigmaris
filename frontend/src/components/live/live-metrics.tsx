// 役割: Sigmaris Live-3/他の処理への拡大(docs/sigmaris/
// sigmaris_live_report.md)。「簡単なメトリクス」の表示(依頼書2章3節)。
// 既存のイベントデータ(metrics.ts)から算出するのみで、新しいデータ収集は
// 一切行わない。データソースを知らない、純粋な表示コンポーネント。
//
// 【他の処理への拡大タスクでの改良(要件5への対応)】
// 即時判定/LLM判定カードは、config.sourceBreakdownLabel(process-
// steps.ts)が設定されているステップのみ表示する——記憶検索・応答生成には
// この内訳の概念自体が無いため(意図分類だけがヒューリスティック/LLMの
// 二択を持つ)、component側でconfig.idによる分岐をせず、config自身が
// 持つデータの有無だけで表示要否を判断する形にした。

import { computeStepMetrics, computeToolCallMetrics } from "./metrics";
import { PROCESS_STEPS } from "./process-steps";
import type { LiveEvent } from "./types";

type MetricCardData = {
  key: string;
  label: string;
  value: string;
};

function buildCards(events: readonly LiveEvent[]): MetricCardData[] {
  const stepCards = PROCESS_STEPS.flatMap((config) => {
    const m = computeStepMetrics(events, config);
    const cards: MetricCardData[] = [
      {
        key: `${config.id}-last`,
        label: `${config.label}・直近の所要時間`,
        value: m.lastElapsedMs === null ? "—" : `${m.lastElapsedMs}ms`,
      },
      {
        key: `${config.id}-avg`,
        label: `${config.label}・平均(直近${m.sampleCount}件)`,
        value: m.averageElapsedMs === null ? "—" : `${m.averageElapsedMs}ms`,
      },
    ];
    if (config.sourceBreakdownLabel) {
      cards.push(
        {
          key: `${config.id}-heuristic`,
          label: `${config.label}・${config.sourceBreakdownLabel.heuristic}`,
          value: `${m.heuristicCount}件`,
        },
        {
          key: `${config.id}-llm`,
          label: `${config.label}・${config.sourceBreakdownLabel.llm}`,
          value: `${m.llmCount}件`,
        },
      );
    }
    return cards;
  });

  const toolCall = computeToolCallMetrics(events);
  const toolCallCards: MetricCardData[] =
    toolCall.callCount > 0
      ? [
          { key: "tool_call-count", label: "ツール実行・件数", value: `${toolCall.callCount}件` },
          { key: "tool_call-success", label: "ツール実行・成功", value: `${toolCall.successCount}件` },
          { key: "tool_call-failure", label: "ツール実行・失敗", value: `${toolCall.failureCount}件` },
        ]
      : [];

  return [...stepCards, ...toolCallCards];
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col justify-between gap-2 rounded-2xl border border-white/10 bg-[#212121] p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-[#8e8ea0]">{label}</p>
      <p className="text-lg font-semibold text-[#ececec]">{value}</p>
    </div>
  );
}

export function LiveMetrics({ events }: { events: LiveEvent[] }) {
  const cards = buildCards(events);
  const hasAnyData = cards.some((card) => card.value !== "—" && card.value !== "0件");

  return (
    <div className="rounded-3xl border border-white/10 bg-[#2a2a2a] p-4 shadow-[0_18px_60px_-45px_rgba(0,0,0,0.75)] sm:p-5">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-[#ececec] sm:text-lg">メトリクス</h2>
        <p className="mt-1 text-sm leading-6 text-[#8e8ea0]">
          既に受信したイベントから算出した、簡単な統計です。新しいデータ収集は行っていません。
        </p>
      </div>
      {!hasAnyData ? (
        <p className="text-sm text-[#8e8ea0]">まだデータがありません。/chatで会話すると表示されます。</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {cards.map((card) => (
            <MetricCard key={card.key} label={card.label} value={card.value} />
          ))}
        </div>
      )}
    </div>
  );
}
