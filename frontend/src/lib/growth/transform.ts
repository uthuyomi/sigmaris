// 役割: /growthページ(フロントエンド成長ログ)が表示する、5指標の整形ロジック。
//
// /timelineのlib/timeline/transform.tsと同じ理由(フレームワーク非依存の
// 純粋関数として切り出し、npx tsx等で直接検証可能にする/データ整形と
// プレゼンテーションの関心分離)で、ページ本体から切り出している。

export type CycleHealthRun = {
  id?: string;
  run_at?: string | null;
  rc1_eligible_completion_rate?: number | null;
  rc2_score?: number | null;
  rc5_status?: string | null;
  rc5_broke_metrics?: string[] | null;
  safety_governance_status?: string | null;
  safety_governance_unregistered_count?: number | null;
};

export type GroundingHealthRun = {
  id?: string;
  run_at?: string | null;
  citation_precision?: number | null;
  contradiction_rate?: number | null;
};

export type DriveStateSnapshot = {
  knowledge_gap: { level: number };
  mastery: { level: number | null; has_data: boolean };
  coherence: { level: number };
};

export type PendingReviewSummary = {
  migration_review_pending_count: number;
  code_diff_pending_count: number;
  total_pending_count: number;
};

export type StatusTone = "good" | "attention" | "neutral";

export type StatusDisplay = {
  label: string;
  tone: StatusTone;
};

// docs/sigmaris/phase_r_report.md(RC-5): insufficient_historyは「異常
// なし」ではなく「履歴不足で未判定」——healthyと混同してはならない。
export function rc5StatusDisplay(status?: string | null): StatusDisplay {
  switch (status) {
    case "healthy":
      return { label: "健全", tone: "good" };
    case "break_detected":
      return { label: "注意", tone: "attention" };
    case "insufficient_history":
      return { label: "測定中(履歴不足)", tone: "neutral" };
    default:
      return { label: "未測定", tone: "neutral" };
  }
}

// docs/sigmaris/safety_governance_report.md(Safety-3): gap_detectedは
// 「安全上重要なファイルの追加漏れの可能性」を意味し、直ちに危険という
// わけではないが、人間の確認を要する。
export function safetyGovernanceStatusDisplay(status?: string | null): StatusDisplay {
  switch (status) {
    case "healthy":
      return { label: "健全", tone: "good" };
    case "gap_detected":
      return { label: "要確認", tone: "attention" };
    default:
      return { label: "未測定", tone: "neutral" };
  }
}

export function formatPercent(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "N/A";
  return `${Math.round(value * 100)}%`;
}

export function formatRelativeDays(value?: string | null, now: number = Date.now()): string {
  if (!value) return "未測定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未測定";
  const days = Math.floor((now - date.getTime()) / 86_400_000);
  if (days <= 0) return "本日";
  if (days === 1) return "1日前";
  return `${days}日前`;
}

// runsは常に新しい順(APIの並び順)で渡ってくる想定。折れ線グラフは古い
// →新しいの順で描画したいため反転する。値がnullの点はグラフの欠測点
// として扱う(0で埋めない——0%と「未測定」を混同しないため、Phase R/G
// 全体で一貫して守られてきた設計判断をここでも踏襲する)。
export type GroundingTrendPoint = {
  label: string;
  citation_precision: number | null;
  contradiction_rate: number | null;
};

export function buildGroundingTrendPoints(runs: GroundingHealthRun[]): GroundingTrendPoint[] {
  return runs
    .slice()
    .reverse()
    .map((run) => ({
      label: shortDateLabel(run.run_at),
      citation_precision:
        typeof run.citation_precision === "number" && !Number.isNaN(run.citation_precision)
          ? run.citation_precision
          : null,
      contradiction_rate:
        typeof run.contradiction_rate === "number" && !Number.isNaN(run.contradiction_rate)
          ? run.contradiction_rate
          : null,
    }));
}

export function shortDateLabel(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("ja-JP", { month: "2-digit", day: "2-digit" }).format(date);
}

export function driveLevelPercent(level: number | null | undefined): number {
  if (typeof level !== "number" || Number.isNaN(level)) return 0;
  return Math.round(Math.min(1, Math.max(0, level)) * 100);
}
