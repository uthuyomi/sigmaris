// 役割: Sigmaris Live-3/他の処理への拡大(docs/sigmaris/
// sigmaris_live_report.md)。ログ表示(依頼書2章「時刻・処理名・簡単な
// 結果が見やすく並ぶログ表示」)。
//
// Live-2からの変更点: 本コンポーネント自体がSSE接続を持つ設計から、
// events(既に受信済みの配列)をpropsで受け取るだけの、データソースを
// 知らない純粋な表示コンポーネントへ変更した(依頼書4章「表示ロジックと
// データソースが疎結合な設計」への対応、判断根拠はlive-dashboard.tsx
// 参照)。実際のSSE接続はuse-live-events.ts(LiveDashboardのみが呼ぶ)
// が担う。
//
// 【他の処理への拡大タスクでの改良(要件5への対応)】
// PROCESS_STEPSに含まれる処理(意図分類・記憶検索・応答生成)の処理名
// ラベル・結果要約は、process-steps.ts側のconfig(label・
// summarizeResult)から動的に導出するようにした——Live-3時点の
// EVENT_LABELS/formatResult()が処理ごとにハードコードされていた状態
// から、設定の追加だけで対応できる形へ改めた。tool_call_started/
// finishedのみ、PROCESS_STEPSに含まれない処理(1ターンに0〜複数回発生
// しうるため、process-steps.tsのモデルには馴染まないと判断——判断根拠、
// 報告書に詳述)として、このファイル内で個別に整形する。

import { PROCESS_STEPS } from "./process-steps";
import { PARSE_ERROR_EVENT } from "./use-live-events";
import type { LiveEvent } from "./types";

const STARTED_LABELS: Record<string, string> = {};
const FINISHED_LABELS: Record<string, string> = {};
const FINISHED_SUMMARIZERS: Record<string, (evt: LiveEvent) => string> = {};
for (const step of PROCESS_STEPS) {
  STARTED_LABELS[step.startedEvent] = `${step.label} ・ 開始`;
  FINISHED_LABELS[step.finishedEvent] = `${step.label} ・ 終了`;
  FINISHED_SUMMARIZERS[step.finishedEvent] = step.summarizeResult;
}

// tool_callは、1ターンに0〜複数回発生しうる(他の処理は高々1回)という
// 性質上、PROCESS_STEPS(process-steps.ts)には含めていない——ログでの
// 表示のみ、ここで個別に対応する。
const TOOL_CALL_LABELS: Record<string, string> = {
  tool_call_started: "ツール実行 ・ 開始",
  tool_call_finished: "ツール実行 ・ 終了",
};

function toolCallSummary(evt: LiveEvent): string {
  const toolName = typeof evt.tool_name === "string" ? evt.tool_name : "unknown";
  if (evt.event === "tool_call_started") {
    return `${toolName} を実行中...`;
  }
  const ok = evt.ok === true;
  const elapsed = typeof evt.elapsed_ms === "number" ? ` ・ ${evt.elapsed_ms}ms` : "";
  return `${toolName}(${ok ? "成功" : "失敗"})${elapsed}`;
}

function eventLabel(evt: LiveEvent): string {
  if (evt.event === PARSE_ERROR_EVENT) return "受信エラー";
  return STARTED_LABELS[evt.event] ?? FINISHED_LABELS[evt.event] ?? TOOL_CALL_LABELS[evt.event] ?? evt.event;
}

function formatResult(evt: LiveEvent): string {
  if (evt.event === PARSE_ERROR_EVENT) {
    return "配信データの解析に失敗しました";
  }
  if (evt.event in STARTED_LABELS) {
    return "実行中...";
  }
  const summarize = FINISHED_SUMMARIZERS[evt.event];
  if (summarize) {
    return summarize(evt);
  }
  if (evt.event === "tool_call_started" || evt.event === "tool_call_finished") {
    return toolCallSummary(evt);
  }
  return "—";
}

export function LiveEventLog({ events }: { events: LiveEvent[] }) {
  // 新しいものを上に表示する(ログとして自然な順序)。
  const rows = [...events].reverse();

  return (
    <div className="rounded-3xl border border-white/10 bg-[#2a2a2a] p-4 shadow-[0_18px_60px_-45px_rgba(0,0,0,0.75)] sm:p-5">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-[#ececec] sm:text-lg">ログ</h2>
        <p className="mt-1 text-sm leading-6 text-[#8e8ea0]">
          時刻・処理名・結果を、新しい順に表示します(直近{events.length}件)。
        </p>
      </div>
      <div className="max-h-[50vh] overflow-y-auto rounded-2xl border border-white/10 bg-[#212121]">
        {rows.length === 0 ? (
          <p className="p-4 text-sm text-[#8e8ea0]">
            まだイベントを受信していません。/chatで会話すると、ここに表示されます。
          </p>
        ) : (
          <table className="w-full border-collapse text-sm">
            <tbody>
              {rows.map((evt, idx) => (
                <tr key={`${evt.invocation_id}-${evt.event}-${idx}`} className="border-b border-white/5 last:border-0">
                  <td className="whitespace-nowrap px-3 py-2 align-top font-mono text-xs text-[#8e8ea0]">
                    {new Date(evt.timestamp * 1000).toLocaleTimeString()}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 align-top text-[#ececec]">{eventLabel(evt)}</td>
                  <td className="px-3 py-2 align-top text-[#8e8ea0]">{formatResult(evt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
