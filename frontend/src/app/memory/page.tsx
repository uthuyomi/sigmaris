// 役割: 「記憶」画面。デザイン統一 第四段階で、旧 /memory・/timeline・
// /admin/memory の3ページを、1つのタブ画面(現在地/変遷/生データ)へ統合した
// 唯一の正となる記憶画面。タブ状態は ?tab= で表現し、/timeline・/admin/memory
// はこの画面へリダイレクトする(それぞれ page.tsx 参照)。

import { AppShell } from "@/components/app-shell";
import { CurrentTab } from "@/components/memory/current-tab";
import { MemoryTabs, type MemoryTabKey } from "@/components/memory/memory-tabs";
import { RawTab } from "@/components/memory/raw-tab";
import { TimelineTab } from "@/components/memory/timeline-tab";
import { PageHero } from "@/components/shared";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { readShellSettings } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";

function normalizeTab(value: string | undefined): MemoryTabKey {
  if (value === "timeline") return "timeline";
  if (value === "raw") return "raw";
  return "current";
}

const TAB_BADGES: Record<MemoryTabKey, string> = {
  current: "現在地",
  timeline: "Temporal Layer",
  raw: "開発者用",
};

type MemoryPageProps = {
  searchParams?: Promise<{ tab?: string }>;
};

export default async function MemoryPage({ searchParams }: MemoryPageProps) {
  const user = await requireUser("/memory");
  const [{ locale, theme }, authHeaders, resolvedParams] = await Promise.all([
    readShellSettings(user.id),
    readBackendAuthHeaders(),
    searchParams ? searchParams : Promise.resolve(undefined),
  ]);
  const tab = normalizeTab(resolvedParams?.tab);

  return (
    <AppShell
      locale={locale}
      title={locale === "ja" ? "記憶" : "Memory"}
      description={
        locale === "ja"
          ? "シグマリスが覚えている事実・傾向・自己モデル・物語と、その時間変遷・生データ"
          : "Facts, trends, self-model, narrative, plus temporal changes and raw data"
      }
      badge={TAB_BADGES[tab]}
      theme={theme}
    >
      <div className="min-h-full bg-background px-3 py-4 text-foreground sm:px-5 lg:px-6">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-5 pb-4">
          <PageHero
            title="シグマリスの記憶"
            description="会話と観測から更新される家庭支援AIの現在地・変遷・生データを、タブで切り替えて確認できます。"
          />

          <MemoryTabs active={tab} />

          {tab === "current" ? <CurrentTab authHeaders={authHeaders} /> : null}
          {tab === "timeline" ? <TimelineTab authHeaders={authHeaders} /> : null}
          {tab === "raw" ? <RawTab authHeaders={authHeaders} /> : null}
        </div>
      </div>
    </AppShell>
  );
}
