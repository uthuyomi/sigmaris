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
// 【Live-7(デモモード)での拡張】
// Live-3時点の予告通り、同じ{events, status}の形を返す別のフック
// (use-mock-live-events.ts::useMockLiveEvents())を用意し、demoModeの
// 値に応じて、どちらのフックの結果を使うかだけを、本コンポーネントで
// 切り替える(Reactのフックはどちらも無条件に呼び出し、結果だけを選ぶ
// ——条件付きフック呼び出しは、Reactのルール違反になるため)。
// LiveProcessFlow/LiveMetrics/LiveEventLogの3つは、この切り替えの存在を
// 一切知らず、無変更のまま動作する——依頼書の必須要件2への対応の実体。

import { LiveEventLog } from "./live-event-log";
import { LiveMetrics } from "./live-metrics";
import { LiveProcessFlow } from "./live-process-flow";
import { useLiveEvents } from "./use-live-events";
import { useMockLiveEvents } from "./use-mock-live-events";
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

export function LiveDashboard({ demoMode = false }: { demoMode?: boolean }) {
  const live = useLiveEvents(undefined, { enabled: !demoMode });
  const mock = useMockLiveEvents({ enabled: demoMode });
  const { events, status } = demoMode ? mock : live;

  return (
    <div className="relative flex flex-col gap-4">
      <p className="text-sm text-[#8e8ea0]">
        接続状態: <span className={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</span>
        {demoMode && <span className="ml-2 text-[#8e8ea0]">(デモモード:模擬データを再生中)</span>}
      </p>
      <LiveProcessFlow events={events} />
      <LiveMetrics events={events} />
      <LiveEventLog events={events} />
      {demoMode && (
        // 依頼書3章「控えめな注記」への対応:動画撮影・スクリーンショット
        // に写り込む前提だが、画面の隅に小さく表示するのみに留め、内容の
        // 邪魔をしない/動画編集時に容易に切り取れる位置にした。
        <span className="pointer-events-none absolute bottom-2 right-2 rounded-full border border-white/10 bg-black/40 px-2 py-0.5 text-[10px] text-[#8e8ea0]">
          デモ用の模擬データです
        </span>
      )}
    </div>
  );
}
