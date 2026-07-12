// 役割: Temporal Layer(event/state/trait)の時間的な変遷を表示するNext.jsページ。

import { AppShell } from "@/components/app-shell";
import { EventVolumeChart } from "@/components/timeline/event-volume-chart";
import { StateHistoryDisclosure } from "@/components/timeline/state-history-disclosure";
import { fetchAgentJson } from "@/lib/backend/agent-client";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { readShellSettings } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";
import {
  buildEventVolumeSeries,
  buildStateChains,
  clampConfidence,
  daysSince,
  EVENT_TTL_DAYS,
  formatDate,
  formatValue,
  partitionActiveItems,
  sortPatterns,
  type FactItem,
  type PreferencePattern,
} from "@/lib/timeline/transform";

// Phase: /timelineページ(棚卸し調査で発見された空スキャフォールドの実装)。
// B5(/admin/memory)が「鮮度・矛盾を確認する開発者向けダッシュボード」である
// のに対し、このページは「記憶の時間的な変遷を眺める、一般利用向けページ」
// という役割分担を意図している(依頼書1節)。データソースは同じ
// user_fact_items/sigmaris_user_preference_patternsだが、B5が生データを
// テーブルで一覧表示するのに対し、ここではevent/state/traitという
// Temporal Layerの分類軸に沿って再構成し、supersedeチェーンの折りたたみ表示
// やevent件数の推移グラフなど、変遷を追いやすい見せ方を優先している。

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.06] px-2.5 py-1 text-xs font-medium text-[#ececec]">
      {children}
    </span>
  );
}

function ConfidenceBar({ value }: { value: unknown }) {
  const confidence = clampConfidence(value);
  const percent = Math.round(confidence * 100);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs text-[#8e8ea0]">
        <span>確信度</span>
        <span>{confidence.toFixed(2)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full bg-[#9b59b6]" style={{ width: `${percent}%` }} />
      </div>
    </div>
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

// event: TTL(90日)を基準にした減衰の目安を、進捗バー+文言で表示する。
// B17の実際の減衰計算(confidence×importance_score等)を再現するのではなく、
// 依頼書が明示した「生成から90日でTTLの対象になることが分かるように」と
// いう要件に沿った、単純な経過日数の可視化にとどめている(判断根拠として
// 報告書に明記)。
function EventDecayIndicator({ createdAt }: { createdAt?: string | null }) {
  const elapsed = daysSince(createdAt);
  if (elapsed === null) return null;

  const percent = Math.min(100, Math.round((elapsed / EVENT_TTL_DAYS) * 100));
  const remaining = EVENT_TTL_DAYS - elapsed;
  const label =
    remaining > 0
      ? `生成から${elapsed}日経過(あと${remaining}日で自然に薄れる目安)`
      : `生成から${elapsed}日経過(自然減衰の目安を超えています)`;

  return (
    <div className="mt-3 space-y-1.5">
      <p className="text-xs text-[#8e8ea0]">{label}</p>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
        <div
          className={remaining > 0 ? "h-full rounded-full bg-[#9b59b6]" : "h-full rounded-full bg-[#e07856]"}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

export default async function TimelinePage() {
  const user = await requireUser("/timeline");
  const { locale, theme } = await readShellSettings(user.id);
  const authHeaders = await readBackendAuthHeaders();

  const [factsResult, patternsResult] = await Promise.all([
    fetchAgentJson<{ items?: FactItem[] }>("/api/agent/facts/items", authHeaders),
    fetchAgentJson<{ patterns?: PreferencePattern[] }>(
      "/api/agent/preference-patterns/list",
      authHeaders,
    ),
  ]);

  const { events, states, traitFacts } = partitionActiveItems(factsResult.data?.items ?? []);
  const patterns = sortPatterns(patternsResult.data?.patterns ?? []);
  const stateChains = buildStateChains(states);
  const eventVolumeSeries = buildEventVolumeSeries(events);

  return (
    <AppShell
      locale={locale}
      title={locale === "ja" ? "タイムライン" : "Timeline"}
      description={
        locale === "ja"
          ? "記憶(出来事・状態・傾向)が時間とともにどう積み重なり、変化してきたかを眺めるページです"
          : "See how Sigmaris's event/state/trait memories accumulate and change over time"
      }
      badge="Temporal Layer"
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
                <h1 className="text-2xl font-semibold tracking-tight text-[#ececec]">
                  記憶の時間的な変遷
                </h1>
                <p className="mt-1 text-sm text-[#8e8ea0]">
                  出来事(event)・状態(state)・傾向(trait)、それぞれの時間の流れを確認できます。
                </p>
              </div>
            </div>
          </section>

          <Section
            title="出来事(event)"
            description={`直近の出来事を新しい順に表示します。生成から${EVENT_TTL_DAYS}日を目安に、自然に記憶から薄れていきます。`}
          >
            {factsResult.error ? <ErrorState message={factsResult.error} /> : null}
            {!factsResult.error ? (
              <div className="mb-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#8e8ea0]">
                  週次の出来事件数(直近13週)
                </p>
                <EventVolumeChart data={eventVolumeSeries} />
              </div>
            ) : null}
            {!factsResult.error && events.length === 0 ? (
              <EmptyState>記録されているevent種別の記憶はまだありません。</EmptyState>
            ) : null}
            <div className="space-y-2">
              {events.map((event, index) => (
                <article
                  key={event.id ?? `event-${index}`}
                  className="rounded-2xl border border-white/10 bg-[#212121] p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="break-words text-sm font-semibold text-[#ececec]">
                        {event.category ?? "uncategorized"}/{event.key ?? "unknown"}
                      </h3>
                      <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[#d8d8de]">
                        {formatValue(event.value)}
                      </p>
                    </div>
                    <Badge>{formatDate(event.created_at)}</Badge>
                  </div>
                  <EventDecayIndicator createdAt={event.created_at} />
                </article>
              ))}
            </div>
          </Section>

          <Section
            title="状態(state)"
            description="現在有効な状態を一覧表示します。過去に置き換えられた(superseded)状態も、履歴として遡って確認できます。"
          >
            {!factsResult.error && stateChains.length === 0 ? (
              <EmptyState>記録されているstate種別の記憶はまだありません。</EmptyState>
            ) : null}
            <div className="space-y-2">
              {stateChains.map((chain) => (
                <article
                  key={chain.key}
                  className="rounded-2xl border border-white/10 bg-[#212121] p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="break-words text-sm font-semibold text-[#ececec]">
                        {chain.category}/{chain.itemKey}
                      </h3>
                      <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[#d8d8de]">
                        {chain.active ? formatValue(chain.active.value) : "現在有効な値はありません"}
                      </p>
                    </div>
                    <Badge>
                      有効開始: {formatDate(chain.active?.valid_from ?? chain.active?.created_at)}
                    </Badge>
                  </div>
                  <StateHistoryDisclosure history={chain.history} />
                </article>
              ))}
            </div>
          </Section>

          <Section
            title="傾向(trait)"
            description="B14が繰り返しのやり取りから抽出した判断傾向と、confidenceを持つtrait種別の事実記憶を表示します。"
          >
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[#cfcfd7]">
                  判断傾向(B14)
                </h3>
                {patternsResult.error ? <ErrorState message={patternsResult.error} /> : null}
                {!patternsResult.error && patterns.length === 0 ? (
                  <EmptyState>検出済みの判断傾向はまだありません。</EmptyState>
                ) : null}
                <div className="space-y-2">
                  {patterns.map((pattern, index) => (
                    <article
                      key={pattern.pattern_key ?? `pattern-${index}`}
                      className="rounded-2xl border border-white/10 bg-[#212121] p-4"
                    >
                      <p className="whitespace-pre-wrap break-words text-sm leading-6 text-[#d8d8de]">
                        {pattern.pattern_statement ?? "説明は未設定です。"}
                      </p>
                      <p className="mt-2 text-xs text-[#8e8ea0]">
                        根拠となった判断: {Number(pattern.evidence_count ?? 0)}件 ・ 最終確認:{" "}
                        {formatDate(pattern.last_confirmed_at)}
                      </p>
                    </article>
                  ))}
                </div>
              </div>

              <div>
                <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[#cfcfd7]">
                  傾向として記録された事実
                </h3>
                {!factsResult.error && traitFacts.length === 0 ? (
                  <EmptyState>memory_kind=&apos;trait&apos;の事実記憶はまだありません。</EmptyState>
                ) : null}
                <div className="space-y-2">
                  {traitFacts.map((trait, index) => (
                    <article
                      key={trait.id ?? `trait-${index}`}
                      className="rounded-2xl border border-white/10 bg-[#212121] p-4"
                    >
                      <h4 className="break-words text-sm font-semibold text-[#ececec]">
                        {trait.category ?? "uncategorized"}/{trait.key ?? "unknown"}
                      </h4>
                      <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[#d8d8de]">
                        {formatValue(trait.value)}
                      </p>
                      <div className="mt-3">
                        <ConfidenceBar value={trait.confidence} />
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            </div>
          </Section>
        </div>
      </div>
    </AppShell>
  );
}
