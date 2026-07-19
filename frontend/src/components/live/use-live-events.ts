"use client";

// 役割: Sigmaris Live-3(docs/sigmaris/sigmaris_live_report.md)。実際の
// SSE接続を行う、唯一の場所。
//
// 【依頼書4章「表示ロジックとデータソースが疎結合な設計」への対応
// (判断根拠)】
// LiveProcessFlow・LiveMetrics・LiveEventLog(いずれも本タスクで実装)は、
// このフックを直接呼ばず、events配列をpropsとして受け取るだけの、純粋な
// 表示コンポーネントにした。データソースを知っているのは、このフックと、
// それを呼ぶLiveDashboard(live-dashboard.tsx)だけである。将来のLive-7
// (個人情報を含まない模擬データでの表示)では、同じ{events, status}の
// 形を返す別のフック(例: useMockLiveEvents())を用意し、LiveDashboard側
// で呼び分けるだけで対応できる——3つの表示コンポーネントは無変更で
// 動作する設計にした。

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

export function useLiveEvents(streamUrl: string = "/api/live/stream"): UseLiveEventsResult {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [status, setStatus] = useState<LiveConnectionStatus>("connecting");

  useEffect(() => {
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
  }, [streamUrl]);

  return { events, status };
}
