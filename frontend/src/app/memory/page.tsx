import { AppShell } from "@/components/app-shell";
import { getBackendBaseUrl } from "@/lib/backend/client";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { readShellSettings } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";
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

type ApiResult<T> = {
  data: T | null;
  error: string | null;
};

type AgentHeaders = {
  "x-agent-id": string;
  "x-agent-secret": string;
};

const toneLabels: Record<string, string> = {
  curious: "好奇心",
  growing: "成長中",
  stable: "安定",
  questioning: "問い直し",
};

function readAgentHeaders(): AgentHeaders | null {
  const directId =
    process.env.AGENT_ID ??
    process.env.SIGMARIS_AGENT_ID ??
    process.env.SCHEDULE_AGENT_ID ??
    process.env.NEXT_PRIVATE_AGENT_ID;
  const directSecret =
    process.env.AGENT_SECRET ??
    process.env.SIGMARIS_AGENT_SECRET ??
    process.env.SCHEDULE_AGENT_SECRET ??
    process.env.NEXT_PRIVATE_AGENT_SECRET;

  if (directId && directSecret) {
    return {
      "x-agent-id": directId,
      "x-agent-secret": directSecret,
    };
  }

  const rawSecrets = process.env.AGENT_SECRETS;
  if (!rawSecrets) return null;

  try {
    const parsed = JSON.parse(rawSecrets) as Record<string, string>;
    const preferredId = directId ?? Object.keys(parsed)[0];
    const secret = preferredId ? parsed[preferredId] : undefined;
    if (!preferredId || !secret) return null;

    return {
      "x-agent-id": preferredId,
      "x-agent-secret": secret,
    };
  } catch {
    return null;
  }
}

async function fetchAgentJson<T>(
  path: string,
  headers: Record<string, string>,
  init?: RequestInit,
): Promise<ApiResult<T>> {
  const agentHeaders = readAgentHeaders();
  if (!agentHeaders) {
    return {
      data: null,
      error: "AGENT_SECRETS またはエージェント認証用の環境変数が未設定です。",
    };
  }

  try {
    const response = await fetch(`${getBackendBaseUrl()}${path}`, {
      ...init,
      headers: {
        ...headers,
        ...agentHeaders,
        ...(init?.headers as Record<string, string> | undefined),
      },
      cache: "no-store",
    });

    if (!response.ok) {
      const detail = await response.text();
      return {
        data: null,
        error: `取得に失敗しました (${response.status})${detail ? `: ${detail.slice(0, 180)}` : ""}`,
      };
    }

    return {
      data: (await response.json()) as T,
      error: null,
    };
  } catch (error) {
    return {
      data: null,
      error: error instanceof Error ? error.message : "不明なエラーが発生しました。",
    };
  }
}

async function reflectNow() {
  "use server";

  await fetchAgentJson("/api/agent/self/reflect", {}, { method: "POST" });
  revalidatePath("/memory");
}

function clampConfidence(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.min(1, Math.max(0, numeric));
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
        <div
          className="h-full rounded-full bg-[#9b59b6]"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.06] px-2.5 py-1 text-xs font-medium text-[#ececec]">
      {children}
    </span>
  );
}

function Section({
  title,
  description,
  children,
  action,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-white/10 bg-[#2a2a2a] p-4 shadow-[0_18px_60px_-45px_rgba(0,0,0,0.75)] sm:p-5">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-[#ececec] sm:text-lg">{title}</h2>
          <p className="mt-1 text-sm leading-6 text-[#8e8ea0]">{description}</p>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}

export default async function MemoryPage() {
  const user = await requireUser("/memory");
  const { locale, theme } = await readShellSettings(user.id);
  const authHeaders = await readBackendAuthHeaders();

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
    <AppShell
      locale={locale}
      title={locale === "ja" ? "記憶" : "Memory"}
      description={
        locale === "ja"
          ? "シグマリスが覚えている事実、傾向、自己モデル、自己物語"
          : "Facts, trends, self-model, and narrative remembered by Sigmaris"
      }
      badge={locale === "ja" ? "同期中" : "Live"}
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
                  シグマリスの記憶
                </h1>
                <p className="mt-1 text-sm text-[#8e8ea0]">
                  会話と観測から更新される家庭支援AIの現在地です。
                </p>
              </div>
            </div>
          </section>

          <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
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
                      <h3 className="text-sm font-semibold uppercase tracking-wide text-[#cfcfd7]">
                        {category}
                      </h3>
                      <span className="text-xs text-[#8e8ea0]">{items.length}件</span>
                    </div>
                    <div className="space-y-2">
                      {items.map((item, index) => (
                        <article
                          key={item.id ?? `${category}-${item.key ?? index}`}
                          className="rounded-2xl border border-white/10 bg-[#212121] p-4"
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0">
                              <h4 className="break-words text-sm font-semibold text-[#ececec]">
                                {item.key || "unknown"}
                              </h4>
                              <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[#d8d8de]">
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

            <div className="space-y-4">
              <Section
                title="自己モデル"
                description="シグマリスが自分自身をどう捉えているかを表示します。"
                action={
                  <form action={reflectNow}>
                    <button className="rounded-full bg-[#9b59b6] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#ad6bc7]">
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
                    <blockquote className="rounded-2xl border border-[#9b59b6]/30 bg-[#9b59b6]/10 px-4 py-4 text-base font-medium leading-8 text-[#f1e8f6]">
                      {selfModel.identity_statement || "identity_statement は未設定です。"}
                    </blockquote>
                    <div>
                      <h3 className="mb-2 text-sm font-semibold text-[#ececec]">
                        current_goals
                      </h3>
                      {goals.length > 0 ? (
                        <ul className="space-y-2">
                          {goals.map((goal, index) => (
                            <li
                              key={`${goal}-${index}`}
                              className="rounded-2xl border border-white/10 bg-[#212121] px-4 py-3 text-sm leading-6 text-[#d8d8de]"
                            >
                              {goal}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <EmptyState>現在の目標は未設定です。</EmptyState>
                      )}
                    </div>
                    <div className="grid gap-2 text-sm text-[#8e8ea0] sm:grid-cols-2">
                      <div className="rounded-2xl bg-white/[0.04] px-4 py-3">
                        version: {selfModel.version ?? "未記録"}
                      </div>
                      <div className="rounded-2xl bg-white/[0.04] px-4 py-3">
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
                      <h3 className="text-lg font-semibold text-[#ececec]">
                        {narrative.title || "無題"}
                      </h3>
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-[#d8d8de]">
                        {narrative.summary || "summary は未設定です。"}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-[#212121] px-4 py-4">
                      <p className="text-xs font-semibold uppercase tracking-wide text-[#8e8ea0]">
                        self_reflection
                      </p>
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-[#ececec]">
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
                  className="rounded-2xl border border-white/10 bg-[#212121] p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>{trend.category || "uncategorized"}</Badge>
                    <span className="text-xs text-[#8e8ea0]">
                      {formatDate(trend.detected_at ?? trend.last_updated_at)}
                    </span>
                  </div>
                  <h3 className="mt-3 break-words text-sm font-semibold text-[#ececec]">
                    {trend.trend_key || "unknown_trend"}
                  </h3>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[#d8d8de]">
                    {trend.trend_description || "説明は未設定です。"}
                  </p>
                  <div className="mt-4">
                    <ConfidenceBar value={trend.confidence} />
                  </div>
                </article>
              ))}
            </div>
          </Section>
        </div>
      </div>
    </AppShell>
  );
}
