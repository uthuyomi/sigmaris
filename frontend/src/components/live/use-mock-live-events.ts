"use client";

// 役割: Sigmaris Live-7(デモモード、docs/sigmaris/sigmaris_live_report.md)。
// X発信・動画撮影用に、実際のSSE接続の代わりに、あらかじめ用意した架空の
// シナリオ(demo-scenarios.ts)を、時間差で再生する。
//
// 【Live-3の疎結合設計をそのまま活かした実装】
// use-live-events.ts::useLiveEvents()と、全く同じ{events, status}の形を
// 返す——LiveDashboard(live-dashboard.tsx)側で、どちらのフックを呼ぶかを
// 切り替えるだけで、LiveProcessFlow・LiveMetrics・LiveEventLogの3つの
// 表示コンポーネントは、一切変更する必要が無い(依頼書の必須要件2への
// 対応)。イベントの形自体も、実際のemit_live_event()が発行するものと
// 完全に同じ構造(event/invocation_id/timestamp+要約フィールド)にして
// あるため、表示コンポーネント側は、データがモックか実データかを区別する
// 手段すら持たない。

import { useEffect, useState } from "react";
import { DEMO_SCENARIOS, DEMO_SCENARIO_GAP_MS, type DemoStep } from "./demo-scenarios";
import type { LiveConnectionStatus, LiveEvent } from "./types";
import type { UseLiveEventsResult } from "./use-live-events";

const MAX_EVENTS = 200;

function randomId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // ブラウザがcrypto.randomUUID()を持たない場合の、簡易フォールバック
  // (架空のIDを組み立てられればよく、暗号学的な強度は不要)。
  return `demo-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildEvent(step: DemoStep, invocationId: string, toolCallId: string | null): LiveEvent {
  return {
    event: step.event,
    invocation_id: invocationId,
    timestamp: Date.now() / 1000,
    ...(step.isToolCall && toolCallId ? { tool_call_id: toolCallId } : {}),
    ...(step.fields ?? {}),
  };
}

export type UseMockLiveEventsOptions = {
  /** falseの場合、再生を一切開始しない(LiveDashboardが、通常モード中に
   * このフックを無駄に走らせないために使う)。 */
  enabled?: boolean;
};

export function useMockLiveEvents({ enabled = true }: UseMockLiveEventsOptions = {}): UseLiveEventsResult {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  // デモは実際の接続を張らないため、待たせる理由がない——real hookと
  // 同じ"connecting"始まりにはせず、最初から"open"にしている(effect内で
  // 同期的にsetState()するとカスケード再描画を招くというeslintの指摘
  // (react-hooks/set-state-in-effect)にも、この形なら抵触しない)。
  const [status] = useState<LiveConnectionStatus>("open");

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    async function playForever() {
      let scenarioIndex = 0;
      while (!cancelled) {
        const scenario = DEMO_SCENARIOS[scenarioIndex % DEMO_SCENARIOS.length];
        const invocationId = randomId();
        let toolCallId: string | null = null;

        for (const step of scenario.steps) {
          await sleep(step.delayMs);
          if (cancelled) return;
          if (step.isToolCall && !toolCallId) {
            toolCallId = randomId();
          }
          const evt = buildEvent(step, invocationId, toolCallId);
          setEvents((prev) => [...prev.slice(-(MAX_EVENTS - 1)), evt]);
        }

        await sleep(DEMO_SCENARIO_GAP_MS);
        scenarioIndex += 1;
      }
    }

    playForever();

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return { events, status };
}
