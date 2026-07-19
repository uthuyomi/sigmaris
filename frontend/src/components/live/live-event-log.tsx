// 役割: Sigmaris Live-3(docs/sigmaris/sigmaris_live_report.md)。ログ表示
// (依頼書2章「時刻・処理名・簡単な結果が見やすく並ぶログ表示」)。
//
// Live-2からの変更点: 本コンポーネント自体がSSE接続を持つ設計から、
// events(既に受信済みの配列)をpropsで受け取るだけの、データソースを
// 知らない純粋な表示コンポーネントへ変更した(依頼書4章「表示ロジックと
// データソースが疎結合な設計」への対応、判断根拠はlive-dashboard.tsx
// 参照)。実際のSSE接続はuse-live-events.ts(LiveDashboardのみが呼ぶ)
// が担う。

import { PARSE_ERROR_EVENT } from "./use-live-events";
import type { LiveEvent } from "./types";

const EVENT_LABELS: Record<string, string> = {
  intent_classification_started: "意図分類 ・ 開始",
  intent_classification_finished: "意図分類 ・ 終了",
  [PARSE_ERROR_EVENT]: "受信エラー",
};

function formatResult(evt: LiveEvent): string {
  if (evt.event === PARSE_ERROR_EVENT) {
    return "配信データの解析に失敗しました";
  }
  if (evt.event === "intent_classification_started") {
    return "実行中...";
  }
  if (evt.event === "intent_classification_finished") {
    const intent = typeof evt.intent === "string" ? evt.intent : "unknown";
    const source = evt.source === "llm" ? "LLM判定" : "即時判定";
    const needsSearch = evt.needs_search ? "・検索要" : "";
    const elapsed = typeof evt.elapsed_ms === "number" ? `${evt.elapsed_ms}ms` : "—";
    return `${intent}(${source}${needsSearch}) ・ ${elapsed}`;
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
                  <td className="whitespace-nowrap px-3 py-2 align-top text-[#ececec]">
                    {EVENT_LABELS[evt.event] ?? evt.event}
                  </td>
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
