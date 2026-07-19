"use client";

// 役割: Sigmaris Live-3(docs/sigmaris/sigmaris_live_report.md)。実際の
// SSE接続を行う、唯一の場所。
//
// 【依頼書4章「表示ロジックとデータソースが疎結合な設計」への対応
// (判断根拠)】
// LiveProcessFlow・LiveMetrics・LiveEventLog(いずれも本タスクで実装)は、
// このフックを直接呼ばず、events配列をpropsとして受け取るだけの、純粋な
// 表示コンポーネントにした。データソースを知っているのは、このフックと、
// それを呼ぶLiveDashboard(live-dashboard.tsx)だけである。
//
// 【Live-7(デモモード)での拡張】
// Live-3時点の予告通り、同じ{events, status}の形を返す別のフック
// (use-mock-live-events.ts::useMockLiveEvents())を用意し、LiveDashboard
// 側で呼び分けるだけで、デモモードに対応した——3つの表示コンポーネントは
// 無変更のまま動作する。本フック自身への変更は、デモモード中に無駄な
// 実SSE接続を張らないための`enabled`オプションの追加のみ(既定値true、
// 呼び出し方を変えない限り、既存の挙動から一切変わらない)。

import { useEffect, useState } from "react";
import type { LiveConnectionStatus, LiveEvent } from "./types";

// 確認用途のLive-2から変更していない上限(直近200件のみ保持)。
const MAX_EVENTS = 200;

// SSEのdataが壊れていた場合の、ログ表示専用のイベント種別。
// computeStepStates/computeStepMetricsは、このevent種別を、既知の
// started/finishedいずれにも一致しないため自然に無視する(特別扱いの
// 分岐を追加する必要がない)。
export const PARSE_ERROR_EVENT = "_parse_error";

export type UseLiveEventsResult = {
  events: LiveEvent[];
  status: LiveConnectionStatus;
};

export type UseLiveEventsOptions = {
  /** falseの場合、EventSourceを一切開かない(デモモード中、実SSE接続を
   * 無駄に張らないために、LiveDashboardがdemoMode時にfalseを渡す)。 */
  enabled?: boolean;
};

export function useLiveEvents(
  streamUrl: string = "/api/live/stream",
  { enabled = true }: UseLiveEventsOptions = {},
): UseLiveEventsResult {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [status, setStatus] = useState<LiveConnectionStatus>("connecting");

  useEffect(() => {
    if (!enabled) return;

    const source = new EventSource(streamUrl);

    source.onopen = () => setStatus("open");
    source.onerror = () => setStatus("error");
    source.onmessage = (message) => {
      let parsed: LiveEvent;
      try {
        parsed = JSON.parse(message.data) as LiveEvent;
      } catch {
        parsed = {
          event: PARSE_ERROR_EVENT,
          invocation_id: "",
          timestamp: Date.now() / 1000,
          raw: message.data,
        };
      }
      setEvents((prev) => [...prev.slice(-(MAX_EVENTS - 1)), parsed]);
    };

    return () => source.close();
  }, [streamUrl, enabled]);

  return { events, status };
}
