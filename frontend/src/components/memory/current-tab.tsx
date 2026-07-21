// 役割: 「記憶」画面の「現在地」タブの本文(事実記憶・自己モデル・自己物語・
// 傾向記憶)。デザイン統一 第四段階で、旧 /memory ページの本文をタブ本文
// コンポーネントとして切り出したもの(ロジック・見た目は不変、共有部品と
// トークンをそのまま活用)。

import {
  Badge,
  ConfidenceBar,
  EmptyState,
  ErrorState,
  Section,
} from "@/components/shared";
import { fetchAgentJson } from "@/lib/backend/agent-client";
import { revalidatePath } from "next/cache";

type FactItem = {
  id?: string;
  category?: string | null;
  key?: string | null;
  value?: unknown;
  confidence?: number | string | null;
  source?: string | null;
  privacy_level?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
};

type TrendItem = {
  category?: string | null;
  trend_key?: string | null;
  trend_description?: string | null;
  confidence?: number | string | null;
  detected_at?: string | null;
  last_updated_at?: string | null;
};

type SelfModel = {
  identity_statement?: string | null;
  current_goals?: unknown;
  version?: number | string | null;
  last_reflected_at?: string | null;
};

type NarrativeChapter = {
  title?: string | null;
  summary?: string | null;
  self_reflection?: string | null;
  emotional_tone?: string | null;
  chapter?: number | string | null;
  created_at?: string | null;
};

const toneLabels: Record<string, string> = {
  curious: "好奇心",
  growing: "成長中",
  stable: "安定",
  questioning: "問い直し",
};

async function reflectNow() {
  "use server";

  await fetchAgentJson("/api/agent/self/reflect", {}, { method: "POST" });
  revalidatePath("/memory");
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未設定";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function formatDate(value?: string | null): string {
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

function normalizeGoals(value: unknown): string[] {
  if (!value) return [];
  if (Array.isArray(value)) {
    return value.map((item) => formatValue(item)).filter(Boolean);
  }
  if (typeof value === "string") return [value];
  return [formatValue(value)];
}

export async function CurrentTab({ authHeaders }: { authHeaders: Record<string, string> }) {
  const [factsResult, trendsResult, modelResult, narrativeResult] = await Promise.all([
    fetchAgentJson<{ items?: FactItem[] }>("/api/agent/facts/items", authHeaders),
    fetchAgentJson<{ trends?: TrendItem[] }>("/api/agent/trends/list", authHeaders),
    fetchAgentJson<{ model?: SelfModel | null }>("/api/agent/self/model", authHeaders),
    fetchAgentJson<{ chapter?: NarrativeChapter | null }>(
      "/api/agent/narrative/current",
      authHeaders,
    ),
  ]);

  const facts = factsResult.data?.items ?? [];
  const trends = trendsResult.data?.trends ?? [];
  const selfModel = modelResult.data?.model ?? null;
  const narrative = narrativeResult.data?.chapter ?? null;
  const groupedFacts = facts.reduce<Record<string, FactItem[]>>((groups, item) => {
    const category = item.category?.trim() || "uncategorized";
    groups[category] = [...(groups[category] ?? []), item];
    return groups;
  }, {});
  const goals = normalizeGoals(selfModel?.current_goals);

  return (
    <>
      <div className="grid gap-5 lg:grid-cols-[1.15fr_0.85fr]">
        <Section
          title="事実記憶"
          description="プロフィール、健康、生活習慣などの確定的な情報をカテゴリ別に表示します。"
        >
          {factsResult.error ? <ErrorState message={factsResult.error} /> : null}
          {!factsResult.error && facts.length === 0 ? (
            <EmptyState>保存済みの事実記憶はまだありません。</EmptyState>
          ) : null}
          <div className="space-y-4">
            {Object.entries(groupedFacts).map(([category, items]) => (
              <div key={category} className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                    {category}
                  </h3>
                  <span className="text-xs text-muted-foreground">{items.length}件</span>
                </div>
                <div className="space-y-2">
                  {items.map((item, index) => (
                    <article
                      key={item.id ?? `${category}-${item.key ?? index}`}
                      className="rounded-2xl border border-border bg-background p-4"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h4 className="break-words text-sm font-semibold text-foreground">
                            {item.key || "unknown"}
                          </h4>
                          <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-foreground/85">
                            {formatValue(item.value)}
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Badge>{item.privacy_level || "standard"}</Badge>
                          <Badge>{item.source || "unknown"}</Badge>
                        </div>
                      </div>
                      <div className="mt-4">
                        <ConfidenceBar value={item.confidence} />
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Section>

        <div className="space-y-5">
          <Section
            title="自己モデル"
            description="シグマリスが自分自身をどう捉えているかを表示します。"
            action={
              <form action={reflectNow}>
                <button className="rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition hover:bg-primary/85">
                  今すぐ自己反省
                </button>
              </form>
            }
          >
            {modelResult.error ? <ErrorState message={modelResult.error} /> : null}
            {!modelResult.error && !selfModel ? (
              <EmptyState>自己モデルはまだ作成されていません。</EmptyState>
            ) : null}
            {selfModel ? (
              <div className="space-y-5">
                <blockquote className="rounded-2xl border border-primary/30 bg-primary/10 px-4 py-4 text-base font-medium leading-8 text-foreground">
                  {selfModel.identity_statement || "identity_statement は未設定です。"}
                </blockquote>
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-foreground">current_goals</h3>
                  {goals.length > 0 ? (
                    <ul className="space-y-2">
                      {goals.map((goal, index) => (
                        <li
                          key={`${goal}-${index}`}
                          className="rounded-2xl border border-border bg-background px-4 py-3 text-sm leading-6 text-foreground/85"
                        >
                          {goal}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState>現在の目標は未設定です。</EmptyState>
                  )}
                </div>
                <div className="grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
                  <div className="rounded-2xl bg-muted/50 px-4 py-3">
                    version: {selfModel.version ?? "未記録"}
                  </div>
                  <div className="rounded-2xl bg-muted/50 px-4 py-3">
                    last_reflected_at: {formatDate(selfModel.last_reflected_at)}
                  </div>
                </div>
              </div>
            ) : null}
          </Section>

          <Section
            title="自己物語"
            description="シグマリスが直近の変化をどんな章として捉えているか。"
          >
            {narrativeResult.error ? <ErrorState message={narrativeResult.error} /> : null}
            {!narrativeResult.error && !narrative ? (
              <EmptyState>自己物語はまだ生成されていません。</EmptyState>
            ) : null}
            {narrative ? (
              <article className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>
                    {toneLabels[narrative.emotional_tone || ""] ??
                      narrative.emotional_tone ??
                      "tone未設定"}
                  </Badge>
                  {narrative.chapter ? <Badge>chapter {narrative.chapter}</Badge> : null}
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-foreground">
                    {narrative.title || "無題"}
                  </h3>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-foreground/85">
                    {narrative.summary || "summary は未設定です。"}
                  </p>
                </div>
                <div className="rounded-2xl border border-border bg-background px-4 py-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    self_reflection
                  </p>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-foreground">
                    {narrative.self_reflection || "self_reflection は未設定です。"}
                  </p>
                </div>
              </article>
            ) : null}
          </Section>
        </div>
      </div>

      <Section
        title="傾向記憶"
        description="繰り返し見られる行動や生活パターンを、確信度の高い順に表示します。"
      >
        {trendsResult.error ? <ErrorState message={trendsResult.error} /> : null}
        {!trendsResult.error && trends.length === 0 ? (
          <EmptyState>検出済みの傾向記憶はまだありません。</EmptyState>
        ) : null}
        <div className="grid gap-3 md:grid-cols-2">
          {trends.map((trend, index) => (
            <article
              key={`${trend.category ?? "trend"}-${trend.trend_key ?? index}`}
              className="rounded-2xl border border-border bg-background p-4"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{trend.category || "uncategorized"}</Badge>
                <span className="text-xs text-muted-foreground">
                  {formatDate(trend.detected_at ?? trend.last_updated_at)}
                </span>
              </div>
              <h3 className="mt-3 break-words text-sm font-semibold text-foreground">
                {trend.trend_key || "unknown_trend"}
              </h3>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/85">
                {trend.trend_description || "説明は未設定です。"}
              </p>
              <div className="mt-4">
                <ConfidenceBar value={trend.confidence} />
              </div>
            </article>
          ))}
        </div>
      </Section>
    </>
  );
}
