"use client";

// 役割: Sigmaris Live-3(docs/sigmaris/sigmaris_live_report.md)。実際の
// データソース(use-live-events.ts、SSE接続)を知っている、唯一の
// コンポーネント。
//
// 【依頼書4章「表示ロジックとデータソースが疎結合な設計」への対応
// (判断根拠)】
// LiveProcessFlow・LiveMetrics・LiveEventLog(いずれも本タスクで実装)は、
// いずれもevents配列をpropsとして受け取るだけの、データソースを知らない
// 純粋な表示コンポーネントにした。本コンポーネントだけがuseLiveEvents()
// を呼び、1回のSSE接続で取得したevents配列を、3つの表示コンポーネント
// すべてへ配る(表示コンポーネントごとに個別のSSE接続を持たせない設計)。
//
// 将来のLive-7(個人情報を含まない模擬データでの表示)に向けては、この
// コンポーネントを、同じ{events, status}の形を返す別のフック
// (例: useMockLiveEvents())を呼ぶ版に差し替える(またはpage.tsx側で
// 呼び分ける)だけで対応でき、LiveProcessFlow/LiveMetrics/LiveEventLogの
// 3つは無変更のまま動作する——これが本タスクで実現した疎結合の実体である。

import { LiveEventLog } from "./live-event-log";
import { LiveMetrics } from "./live-metrics";
import { LiveProcessFlow } from "./live-process-flow";
import { useLiveEvents } from "./use-live-events";
import type { LiveConnectionStatus } from "./types";

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

export function LiveDashboard() {
  const { events, status } = useLiveEvents();

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-[#8e8ea0]">
        接続状態: <span className={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</span>
      </p>
      <LiveProcessFlow events={events} />
      <LiveMetrics events={events} />
      <LiveEventLog events={events} />
    </div>
  );
}
