"use client";

// 役割: Sigmaris Live を /chat の右サイドバーとして表示するための、
// データソースを知らない純粋な表示コンポーネント(デザイン統一 第五段階、
// docs/sigmaris/sigmaris_live_report.md / frontend_design_unification_report.md)。
//
// 【コード共有・非重複の判断根拠】
// Live-3 で確立した「1つのデータソース(events配列)を複数の表示コンポーネント
// へ配る」設計(live-dashboard.tsx のコメント参照)をそのまま踏襲する。実 SSE
// 接続(useLiveEvents)は呼び出し元(ChatWorkspace)が1回だけ行い、その結果を
// events/status として本パネルへ props で渡す。本パネルは、既存の
// LiveProcessFlow・LiveMetrics・LiveEventLog を"そのまま"縦積みで再利用する
// のみで、新しい表示ロジック・新しいイベント設計は一切持たない(依頼書の制約
// 「既存実装をそのまま再利用」「新しいイベント設計を行わない」への対応)。
// /live の LiveDashboard(フルスクリーン・デモモード対応)とは、同じ3つの葉
// コンポーネントを別レイアウトで composе するだけで、葉コンポーネント自体の
// 重複実装は無い。
//
// 【/chat の既存デザイン・常時ダーク保護との整合】
// 配色は /chat 左サイドバー(SigmarisSidebar)と同じダーク基調(bg-[#171717])。
// 本パネルは ChatWorkspace の .dark サブツリー内に描画されるため、第二段階の
// 常時ダーク保護に自然に乗り、light テーマでもダークのまま。

import { XIcon } from "lucide-react";
import { LiveEventLog } from "./live-event-log";
import { LiveMetrics } from "./live-metrics";
import { LiveProcessFlow } from "./live-process-flow";
import type { LiveConnectionStatus, LiveEvent } from "./types";
import { cn } from "@/lib/utils";

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

export function LiveSidebarPanel({
  events,
  status,
  onClose,
}: {
  events: LiveEvent[];
  status: LiveConnectionStatus;
  onClose?: () => void;
}) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-[#171717] text-[#ececec]">
      <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-white/10 px-3 pt-[env(safe-area-inset-top)]">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-[#9b59b6] text-sm font-semibold text-white">
            Σ
          </span>
          <span className="truncate text-sm font-semibold">Sigmaris Live</span>
          <span className={cn("shrink-0 text-xs", STATUS_COLOR[status])}>● {STATUS_LABEL[status]}</span>
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            aria-label="Liveパネルを閉じる"
            title="閉じる"
            className="flex size-9 shrink-0 items-center justify-center rounded-lg text-[#ececec] transition hover:bg-[#2f2f2f]"
          >
            <XIcon className="size-4" />
          </button>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
        <p className="px-1 text-xs leading-5 text-[#8e8ea0]">
          /chatでメッセージを送ると、その処理(意図分類・記憶検索・応答生成)がここにリアルタイムで表示されます。
        </p>
        <LiveProcessFlow events={events} />
        <LiveMetrics events={events} />
        <LiveEventLog events={events} />
      </div>
    </aside>
  );
}
