// 役割: /timelineページが表示する event/state/trait データの整形ロジック。
//
// Reactやサーバーコンポーネントに依存しない、純粋な関数群としてページ本体
// (app/timeline/page.tsx)から切り出している。理由は2つ:
// (1) このファイル単体で `npx tsx` 等から直接importしてテストできるように
//     するため(フロントエンドにはJest/Vitest等のテストランナーが導入され
//     ていないため、フレームワーク非依存の純粋関数として切り出すことで、
//     追加の依存ライブラリなしに動作検証できるようにした)
// (2) データ整形とプレゼンテーションの関心を分離するため

export type FactItem = {
  id?: string;
  category?: string | null;
  key?: string | null;
  value?: unknown;
  confidence?: number | string | null;
  memory_kind?: string | null;
  valid_from?: string | null;
  superseded_by?: string | null;
  last_mentioned_at?: string | null;
  is_deleted?: boolean | null;
  is_stale?: boolean | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type PreferencePattern = {
  pattern_key?: string | null;
  pattern_statement?: string | null;
  evidence_count?: number | string | null;
  first_detected_at?: string | null;
  last_confirmed_at?: string | null;
};

export type EventVolumePoint = {
  label: string;
  count: number;
};

export type StateHistoryEntry = {
  id: string;
  value: string;
  validFromLabel: string;
  supersededAtLabel: string | null;
};

export type StateChain = {
  key: string;
  category: string;
  itemKey: string;
  active: FactItem | null;
  history: StateHistoryEntry[];
};

export const EVENT_TTL_DAYS = 90;

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未設定";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function formatDate(value?: string | null): string {
  if (!value) return "未記録";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function daysSince(value?: string | null, now: number = Date.now()): number | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return Math.floor((now - date.getTime()) / 86_400_000);
}

export function clampConfidence(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.min(1, Math.max(0, numeric));
}

export function partitionActiveItems(items: FactItem[]) {
  const active = items.filter((item) => !item.is_deleted);
  const events = active
    .filter((item) => item.memory_kind === "event")
    .sort((a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime());
  const states = active.filter((item) => item.memory_kind === "state");
  const traitFacts = active
    .filter((item) => item.memory_kind === "trait")
    .sort((a, b) => clampConfidence(b.confidence) - clampConfidence(a.confidence));

  return { events, states, traitFacts };
}

export function sortPatterns(patterns: PreferencePattern[]): PreferencePattern[] {
  return patterns
    .slice()
    .sort((a, b) => Number(b.evidence_count ?? 0) - Number(a.evidence_count ?? 0));
}

export function buildEventVolumeSeries(
  events: FactItem[],
  now: number = Date.now(),
): EventVolumePoint[] {
  // 直近13週(91日)を週次バケットに分け、各週のevent件数を数える。event
  // のTTLの目安が90日(EVENT_TTL_DAYS)であるため、13週(91日)としてTTL
  // 全体をカバーする幅にしている(12週=84日だと、TTL間際のeventがグラフの
  // 範囲外に出てしまうため)。過度に精緻な時系列処理は避け(Temporal Layer
  // Step1〜3が確立した「シンプルなルールベース」の方針を踏襲)、週の境目は
  // 基準時刻からの7日刻みとしている。
  const weeks = 13;
  const buckets: EventVolumePoint[] = Array.from({ length: weeks }, (_, index) => {
    const weeksAgo = weeks - 1 - index;
    const start = new Date(now - weeksAgo * 7 * 86_400_000);
    return {
      label: `${start.getMonth() + 1}/${start.getDate()}`,
      count: 0,
    };
  });

  for (const event of events) {
    if (!event.created_at) continue;
    const createdAt = new Date(event.created_at).getTime();
    if (Number.isNaN(createdAt)) continue;
    const weeksAgo = Math.floor((now - createdAt) / (7 * 86_400_000));
    const bucketIndex = weeks - 1 - weeksAgo;
    if (bucketIndex >= 0 && bucketIndex < weeks) {
      buckets[bucketIndex].count += 1;
    }
  }

  return buckets;
}

export function buildStateChains(states: FactItem[]): StateChain[] {
  // supersede/superseded_byは常に同一(category, key)内でのみ発生する
  // (upsert_fact_item RPCの分岐ロジック、Temporal Layer Step1)ため、
  // (category, key)でグルーピングしvalid_from/created_at昇順に並べれば、
  // 末尾が常にアクティブな行(superseded_by is null)になる、という単純化
  // した前提で履歴チェーンを構築している。
  const groups = new Map<string, FactItem[]>();
  for (const item of states) {
    const key = `${item.category ?? "uncategorized"}::${item.key ?? "unknown"}`;
    const list = groups.get(key) ?? [];
    list.push(item);
    groups.set(key, list);
  }

  const chains: StateChain[] = [];
  for (const [key, items] of groups.entries()) {
    const sorted = [...items].sort((a, b) => {
      const aTime = new Date(a.valid_from ?? a.created_at ?? 0).getTime();
      const bTime = new Date(b.valid_from ?? b.created_at ?? 0).getTime();
      return aTime - bTime;
    });
    const active = sorted.find((item) => !item.superseded_by) ?? sorted[sorted.length - 1] ?? null;
    const history: StateHistoryEntry[] = sorted
      .filter((item) => item !== active)
      .map((item) => ({
        id: item.id ?? `${key}-${item.created_at ?? Math.random()}`,
        value: formatValue(item.value),
        validFromLabel: formatDate(item.valid_from ?? item.created_at),
        supersededAtLabel: item.superseded_by ? formatDate(item.updated_at) : null,
      }));

    const [category, itemKey] = key.split("::");
    chains.push({ key, category, itemKey, active, history });
  }

  return chains.sort((a, b) => a.key.localeCompare(b.key));
}
