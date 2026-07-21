// 役割: シグマリスの内部的な健全性指標(RC-5、Citation Precision + Contradiction
// Rate、Drive State、自己改善パイプラインの承認待ち件数、Safety Governance状況)
// を、一目で把握できるようにするNext.jsページ(docs/sigmaris/phase_vis_report.md、
// Phase Vis-1〜Vis-2)。
//
// デザイン統一 第一段階(docs/sigmaris/frontend_design_unification_report.md):
// 共通の表示部品(Section/EmptyState/ErrorState/PageHero)を @/components/shared
// から import する形へ変更し、本文の hex 直書きを既存の CSS 変数トークンへ
// 置き換えた(見た目はダークのまま維持)。StatCard/DriveLevelBar/StatusBadge は
// このページ固有(他ページと重複していない)ため、トークン化のみ行いローカルに
// 残した。

import { AppShell } from "@/components/app-shell";
import { TrendLineChart } from "@/components/growth/trend-line-chart";
import { EmptyState, ErrorState, PageHero, Section } from "@/components/shared";
import { fetchAgentJson } from "@/lib/backend/agent-client";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import {
  buildGroundingTrendPoints,
  driveLevelPercent,
  formatPercent,
  formatRelativeDays,
  rc5StatusDisplay,
  safetyGovernanceStatusDisplay,
  type CycleHealthRun,
  type DriveStateSnapshot,
  type GroundingHealthRun,
  type PendingReviewSummary,
  type StatusDisplay,
} from "@/lib/growth/transform";
import { readShellSettings } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";

// Phase Vis-1(docs/sigmaris/phase_vis_report.md 5章)が「/timelineとは
// 別の、新規ページとして実装する」ことを推奨していた判断を、そのまま
// 採用した。/timelineは記憶の内容(event/state/trait)の変遷を見せるのに対し、
// 本ページはシグマリス自身の機能的な健全性・状態を見せる、対象が異なる
// ページである。

function StatusBadge({ status }: { status: StatusDisplay }) {
  const toneClasses: Record<StatusDisplay["tone"], string> = {
    good: "border-emerald-400/25 bg-emerald-500/15 text-emerald-300",
    attention: "border-[#e07856]/30 bg-[#e07856]/15 text-[#e0a088]",
    neutral: "border-border bg-white/[0.06] text-muted-foreground",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${toneClasses[status.tone]}`}
    >
      {status.label}
    </span>
  );
}

function StatCard({
  label,
  children,
  href,
}: {
  label: string;
  children: React.ReactNode;
  href?: string;
}) {
  const content = (
    <div className="flex h-full flex-col justify-between gap-2 rounded-2xl border border-border bg-background p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="text-lg font-semibold text-foreground">{children}</div>
    </div>
  );
  if (!href) return content;
  return (
    <a href={href} className="block transition hover:opacity-80">
      {content}
    </a>
  );
}

function DriveLevelBar({ label, level, note }: { label: string; level: number | null; note?: string }) {
  const percent = driveLevelPercent(level);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {label}
          {note ? <span className="ml-1.5 text-[10px] text-muted-foreground/70">{note}</span> : null}
        </span>
        <span>{level === null ? "未測定" : level.toFixed(2)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full bg-primary" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export default async function GrowthPage() {
  const user = await requireUser("/growth");
  const { locale, theme } = await readShellSettings(user.id);
  const authHeaders = await readBackendAuthHeaders();

  const [cycleHealthResult, groundingHealthResult, driveStateResult, pendingReviewResult] =
    await Promise.all([
      fetchAgentJson<{ runs?: CycleHealthRun[] }>("/api/agent/growth/cycle-health?limit=30", authHeaders),
      fetchAgentJson<{ runs?: GroundingHealthRun[] }>(
        "/api/agent/growth/grounding-health?limit=30",
        authHeaders,
      ),
      fetchAgentJson<{ drive_state?: DriveStateSnapshot }>("/api/agent/growth/drive-state", authHeaders),
      fetchAgentJson<PendingReviewSummary>("/api/agent/growth/pending-review", authHeaders),
    ]);

  const cycleRuns = cycleHealthResult.data?.runs ?? [];
  const groundingRuns = groundingHealthResult.data?.runs ?? [];
  const driveState = driveStateResult.data?.drive_state ?? null;
  const pending = pendingReviewResult.data ?? null;

  const latestCycleRun = cycleRuns[0] ?? null;
  const rc5Status = rc5StatusDisplay(latestCycleRun?.rc5_status);
  const safetyStatus = safetyGovernanceStatusDisplay(latestCycleRun?.safety_governance_status);

  const groundingTrendData = buildGroundingTrendPoints(groundingRuns);

  return (
    <AppShell
      locale={locale}
      title={locale === "ja" ? "成長ログ" : "Growth Log"}
      description={
        locale === "ja"
          ? "循環の健全性・応答品質・自己改善パイプラインの状況を、一目で確認できるページです"
          : "See Sigmaris's cycle health, response grounding quality, and self-improvement pipeline status at a glance"
      }
      badge="Growth Log"
      theme={theme}
    >
      <div className="min-h-full bg-background px-3 py-4 text-foreground sm:px-5 lg:px-6">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-5 pb-4">
          <PageHero
            title="シグマリスの調子"
            description="RC-1〜RC-5・Grounding指標・Drive State・自己改善パイプライン・Safety Governanceを、まとめて確認できます。"
          />

          <Section
            title="総合ステータス"
            description="今、シグマリスが健全に機能しているか、確認すべきことがあるかを、一目で示します。"
          >
            {cycleHealthResult.error ? <ErrorState message={cycleHealthResult.error} /> : null}
            {pendingReviewResult.error ? <ErrorState message={pendingReviewResult.error} /> : null}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard label="循環の健全性(RC-5)">
                <StatusBadge status={rc5Status} />
                {latestCycleRun ? (
                  <p className="mt-2 text-xs font-normal text-muted-foreground">
                    RC-1: {formatPercent(latestCycleRun.rc1_eligible_completion_rate)} ・ RC-2:{" "}
                    {formatPercent(latestCycleRun.rc2_score)}
                  </p>
                ) : null}
              </StatCard>
              <StatCard label="Safety Governance">
                <StatusBadge status={safetyStatus} />
                {latestCycleRun?.safety_governance_unregistered_count ? (
                  <p className="mt-2 text-xs font-normal text-muted-foreground">
                    未登録候補: {latestCycleRun.safety_governance_unregistered_count}件
                  </p>
                ) : null}
              </StatCard>
              <StatCard label="承認待ち">
                {pending ? (
                  <>
                    {pending.total_pending_count}件
                    <p className="mt-2 text-xs font-normal text-muted-foreground">
                      マイグレーション{pending.migration_review_pending_count}件 ・ コード差分
                      {pending.code_diff_pending_count}件
                    </p>
                  </>
                ) : (
                  "N/A"
                )}
              </StatCard>
              <StatCard label="直近の測定">{formatRelativeDays(latestCycleRun?.run_at)}</StatCard>
            </div>
          </Section>

          <Section
            title="Drive State(今、何を気にかけているか)"
            description="Knowledge Gap・Mastery・Coherence、それぞれの内的な緊張度の、現在時点のスナップショットです。過去の値との比較は、現状できません(推移を記録する仕組みがまだないため)。"
          >
            {driveStateResult.error ? <ErrorState message={driveStateResult.error} /> : null}
            {!driveStateResult.error && driveState ? (
              <div className="space-y-4 rounded-2xl border border-border bg-background p-4">
                <DriveLevelBar label="Knowledge Gap" level={driveState.knowledge_gap.level} />
                <DriveLevelBar
                  label="Mastery"
                  level={driveState.mastery.has_data ? driveState.mastery.level : null}
                  note={driveState.mastery.has_data ? undefined : "(RC計測が未実行)"}
                />
                <DriveLevelBar label="Coherence" level={driveState.coherence.level} />
              </div>
            ) : null}
            {!driveStateResult.error && !driveState ? (
              <EmptyState>Drive Stateを取得できませんでした。</EmptyState>
            ) : null}
          </Section>

          <Section
            title="応答品質の推移(Citation Precision / Contradiction Rate)"
            description="引用の忠実性(Citation Precision、高いほど良い)と、矛盾検出率(Contradiction Rate、低いほど良い)の推移です。測定は日次・週次の定期実行時のみ記録されるため、点が疎な場合があります。"
          >
            {groundingHealthResult.error ? <ErrorState message={groundingHealthResult.error} /> : null}
            {!groundingHealthResult.error && groundingRuns.length === 0 ? (
              <EmptyState>まだ記録がありません(run_grounding_health.pyの定期実行を待つ必要があります)。</EmptyState>
            ) : null}
            {!groundingHealthResult.error && groundingRuns.length > 0 ? (
              <>
                <div className="mb-3 flex flex-wrap gap-4 text-sm text-foreground/85">
                  <span>
                    直近のCitation Precision:{" "}
                    <strong className="text-foreground">{formatPercent(groundingRuns[0]?.citation_precision)}</strong>
                  </span>
                  <span>
                    直近のContradiction Rate:{" "}
                    <strong className="text-foreground">{formatPercent(groundingRuns[0]?.contradiction_rate)}</strong>
                  </span>
                </div>
                <TrendLineChart
                  data={groundingTrendData}
                  lines={[
                    { dataKey: "citation_precision", name: "Citation Precision", color: "#9b59b6" },
                    { dataKey: "contradiction_rate", name: "Contradiction Rate", color: "#e07856" },
                  ]}
                />
              </>
            ) : null}
          </Section>
        </div>
      </div>
    </AppShell>
  );
}
