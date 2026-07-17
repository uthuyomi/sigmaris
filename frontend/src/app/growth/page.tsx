// 役割: シグマリスの内部的な健全性指標(RC-5、Citation Precision + Contradiction
// Rate、Drive State、自己改善パイプラインの承認待ち件数、Safety Governance状況)
// を、一目で把握できるようにするNext.jsページ(docs/sigmaris/phase_vis_report.md、
// Phase Vis-1〜Vis-2)。

import { AppShell } from "@/components/app-shell";
import { TrendLineChart } from "@/components/growth/trend-line-chart";
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
// 採用した(本タスクの判断根拠、報告書に詳述)。/timelineは記憶の内容
// (event/state/trait)の変遷を見せるのに対し、本ページはシグマリス自身
// の機能的な健全性・状態を見せる、対象が異なるページである。

function StatusBadge({ status }: { status: StatusDisplay }) {
  const toneClasses: Record<StatusDisplay["tone"], string> = {
    good: "border-emerald-400/25 bg-emerald-500/15 text-emerald-300",
    attention: "border-[#e07856]/30 bg-[#e07856]/15 text-[#e0a088]",
    neutral: "border-white/10 bg-white/[0.06] text-[#8e8ea0]",
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
    <div className="flex h-full flex-col justify-between gap-2 rounded-2xl border border-white/10 bg-[#212121] p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-[#8e8ea0]">{label}</p>
      <div className="text-lg font-semibold text-[#ececec]">{children}</div>
    </div>
  );
  if (!href) return content;
  return (
    <a href={href} className="block transition hover:opacity-80">
      {content}
    </a>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-5 text-sm text-[#8e8ea0]">
      {children}
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-red-400/20 bg-red-500/10 px-4 py-3 text-sm text-red-100">
      {message}
    </div>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-white/10 bg-[#2a2a2a] p-4 shadow-[0_18px_60px_-45px_rgba(0,0,0,0.75)] sm:p-5">
      <div className="mb-4">
        <h2 className="text-base font-semibold text-[#ececec] sm:text-lg">{title}</h2>
        <p className="mt-1 text-sm leading-6 text-[#8e8ea0]">{description}</p>
      </div>
      {children}
    </section>
  );
}

function DriveLevelBar({ label, level, note }: { label: string; level: number | null; note?: string }) {
  const percent = driveLevelPercent(level);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs text-[#8e8ea0]">
        <span>
          {label}
          {note ? <span className="ml-1.5 text-[10px] text-[#6f6f7a]">{note}</span> : null}
        </span>
        <span>{level === null ? "未測定" : level.toFixed(2)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full bg-[#9b59b6]" style={{ width: `${percent}%` }} />
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
      <div className="min-h-full bg-[#212121] px-3 py-4 text-[#ececec] sm:px-5 lg:px-6">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-4">
          <section className="rounded-3xl border border-white/10 bg-[#2f2f2f] px-5 py-6 sm:px-6">
            <div className="flex items-center gap-3">
              <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-[#9b59b6] text-2xl font-semibold text-white">
                Σ
              </div>
              <div className="min-w-0">
                <h1 className="text-2xl font-semibold tracking-tight text-[#ececec]">シグマリスの調子</h1>
                <p className="mt-1 text-sm text-[#8e8ea0]">
                  RC-1〜RC-5・Grounding指標・Drive State・自己改善パイプライン・Safety Governanceを、まとめて確認できます。
                </p>
              </div>
            </div>
          </section>

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
                  <p className="mt-2 text-xs font-normal text-[#8e8ea0]">
                    RC-1: {formatPercent(latestCycleRun.rc1_eligible_completion_rate)} ・ RC-2:{" "}
                    {formatPercent(latestCycleRun.rc2_score)}
                  </p>
                ) : null}
              </StatCard>
              <StatCard label="Safety Governance">
                <StatusBadge status={safetyStatus} />
                {latestCycleRun?.safety_governance_unregistered_count ? (
                  <p className="mt-2 text-xs font-normal text-[#8e8ea0]">
                    未登録候補: {latestCycleRun.safety_governance_unregistered_count}件
                  </p>
                ) : null}
              </StatCard>
              <StatCard label="承認待ち">
                {pending ? (
                  <>
                    {pending.total_pending_count}件
                    <p className="mt-2 text-xs font-normal text-[#8e8ea0]">
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
              <div className="space-y-4 rounded-2xl border border-white/10 bg-[#212121] p-4">
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
                <div className="mb-3 flex flex-wrap gap-4 text-sm text-[#d8d8de]">
                  <span>
                    直近のCitation Precision:{" "}
                    <strong className="text-[#ececec]">{formatPercent(groundingRuns[0]?.citation_precision)}</strong>
                  </span>
                  <span>
                    直近のContradiction Rate:{" "}
                    <strong className="text-[#ececec]">{formatPercent(groundingRuns[0]?.contradiction_rate)}</strong>
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
