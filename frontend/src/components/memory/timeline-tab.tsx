// 役割: 「記憶」画面の「変遷(Timeline)」タブの本文(event/state/trait の
// 時間変遷)。デザイン統一 第四段階で、旧 /timeline ページの本文をタブ本文
// コンポーネントとして切り出したもの(ロジック・見た目は不変)。

import {
  Badge,
  ConfidenceBar,
  EmptyState,
  ErrorState,
  Section,
} from "@/components/shared";
import { EventVolumeChart } from "@/components/timeline/event-volume-chart";
import { StateHistoryDisclosure } from "@/components/timeline/state-history-disclosure";
import { fetchAgentJson } from "@/lib/backend/agent-client";
import {
  buildEventVolumeSeries,
  buildStateChains,
  daysSince,
  EVENT_TTL_DAYS,
  formatDate,
  formatValue,
  partitionActiveItems,
  sortPatterns,
  type FactItem,
  type PreferencePattern,
} from "@/lib/timeline/transform";

// event: TTL(90日)を基準にした減衰の目安を、進捗バー+文言で表示する。
// B17の実際の減衰計算(confidence×importance_score等)を再現するのではなく、
// 「生成から90日でTTLの対象になることが分かるように」という要件に沿った、
// 単純な経過日数の可視化にとどめている。
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
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={remaining > 0 ? "h-full rounded-full bg-primary" : "h-full rounded-full bg-[#e07856]"}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

export async function TimelineTab({ authHeaders }: { authHeaders: Record<string, string> }) {
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
    <>
      <Section
        title="出来事(event)"
        description={`直近の出来事を新しい順に表示します。生成から${EVENT_TTL_DAYS}日を目安に、自然に記憶から薄れていきます。`}
      >
        {factsResult.error ? <ErrorState message={factsResult.error} /> : null}
        {!factsResult.error ? (
          <div className="mb-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
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
              className="rounded-2xl border border-border bg-background p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="break-words text-sm font-semibold text-foreground">
                    {event.category ?? "uncategorized"}/{event.key ?? "unknown"}
                  </h3>
                  <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-foreground/85">
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
              className="rounded-2xl border border-border bg-background p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="break-words text-sm font-semibold text-foreground">
                    {chain.category}/{chain.itemKey}
                  </h3>
                  <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-foreground/85">
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
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
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
                  className="rounded-2xl border border-border bg-background p-4"
                >
                  <p className="whitespace-pre-wrap break-words text-sm leading-6 text-foreground/85">
                    {pattern.pattern_statement ?? "説明は未設定です。"}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    根拠となった判断: {Number(pattern.evidence_count ?? 0)}件 ・ 最終確認:{" "}
                    {formatDate(pattern.last_confirmed_at)}
                  </p>
                </article>
              ))}
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              傾向として記録された事実
            </h3>
            {!factsResult.error && traitFacts.length === 0 ? (
              <EmptyState>memory_kind=&apos;trait&apos;の事実記憶はまだありません。</EmptyState>
            ) : null}
            <div className="space-y-2">
              {traitFacts.map((trait, index) => (
                <article
                  key={trait.id ?? `trait-${index}`}
                  className="rounded-2xl border border-border bg-background p-4"
                >
                  <h4 className="break-words text-sm font-semibold text-foreground">
                    {trait.category ?? "uncategorized"}/{trait.key ?? "unknown"}
                  </h4>
                  <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-foreground/85">
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
    </>
  );
}
