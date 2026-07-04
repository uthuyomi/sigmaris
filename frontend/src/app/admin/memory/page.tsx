import { AppShell } from "@/components/app-shell";
import {
  MemoryDashboardTable,
  type DashboardFactItem,
} from "@/components/memory-dashboard-table";
import { fetchBackendJson, BackendApiError } from "@/lib/backend/client";
import { readBackendAuthHeaders } from "@/lib/backend/auth";
import { readShellSettings } from "@/lib/profile-settings";
import { requireUser } from "@/lib/supabase/auth";

// Phase B5: developer-only memory freshness/contradiction dashboard.
// Deliberately not part of persona.md's chat tone or the main nav — this is
// an operational screen for 海星さん to review memory health, not a
// Sigmaris-voiced surface. Read-only: it never writes to /chat's response
// path (see docs/sigmaris/phase_b5_report.md section 2).

async function loadDashboardItems(): Promise<{
  items: DashboardFactItem[];
  error: string | null;
}> {
  try {
    const authHeaders = await readBackendAuthHeaders();
    const result = await fetchBackendJson<{ items?: DashboardFactItem[] }>(
      "/api/app/memory-dashboard",
      { headers: authHeaders },
    );
    return { items: result.items ?? [], error: null };
  } catch (error) {
    const message =
      error instanceof BackendApiError
        ? error.message
        : error instanceof Error
          ? error.message
          : "不明なエラーが発生しました。";
    return { items: [], error: message };
  }
}

export default async function MemoryDashboardPage() {
  const user = await requireUser("/admin/memory");
  const { locale, theme } = await readShellSettings(user.id);
  const { items, error } = await loadDashboardItems();

  return (
    <AppShell
      locale={locale}
      title="記憶ダッシュボード(開発者用)"
      description="user_fact_itemsの鮮度・矛盾・重要度・出所を一覧できる管理画面です。/chatの応答生成には影響しません。"
      badge="Admin"
      theme={theme}
    >
      <div className="min-h-full bg-[#212121] px-3 py-4 text-[#ececec] sm:px-5 lg:px-6">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-4">
          <section className="rounded-3xl border border-white/10 bg-[#2a2a2a] p-4 shadow-[0_18px_60px_-45px_rgba(0,0,0,0.75)] sm:p-5">
            <h2 className="text-base font-semibold text-[#ececec] sm:text-lg">
              記憶の鮮度・矛盾一覧
            </h2>
            <p className="mt-1 text-sm leading-6 text-[#8e8ea0]">
              各記憶の最終更新日時(再確認・上書きされた時刻を含む)・確信度・重要度・
              矛盾検出フラグ(is_stale)・採用回数・出所(会話スレッド/作成日時)を表示します。
              「最終更新」は、明示的な確認履歴専用のテーブルが存在しないため、記憶が
              最後に書き込まれた(再主張・矛盾検出で調整された)時刻を代理指標として
              使用しています。
            </p>
            {error ? (
              <div className="mt-4 rounded-2xl border border-red-400/20 bg-red-500/10 px-4 py-3 text-sm text-red-100">
                {error}
              </div>
            ) : null}
            <div className="mt-4">
              <MemoryDashboardTable items={items} />
            </div>
          </section>
        </div>
      </div>
    </AppShell>
  );
}
