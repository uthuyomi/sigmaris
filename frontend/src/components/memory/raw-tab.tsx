// 役割: 「記憶」画面の「生データ(開発者向け)」タブの本文。デザイン統一
// 第四段階で、旧 /admin/memory(B5・記憶の鮮度/矛盾ダッシュボード)の本文を
// タブ本文コンポーネントとして切り出したもの。
//
// 【"開発者向け"の性質を統合後も保つための配慮(依頼書の制約)】
// タブ名は「生データ(開発者向け)」とし、本文冒頭にも「やや専門的な内容」で
// ある旨を明示するバッジ・注記を置く。これにより、他タブ(現在地/変遷)が
// 利用者向けの落ち着いた表示であるのに対し、このタブは user_fact_items の
// 生の行(is_stale・importance・出所等)を扱う運用/デバッグ向けであることが
// 一目で伝わるようにした。旧 /admin/memory の hex 直書き配色は、他タブと
// 同じ light/dark 対応のトークンへ置き換えた。

import { Badge, ErrorState, Section } from "@/components/shared";
import {
  MemoryDashboardTable,
  type DashboardFactItem,
} from "@/components/memory-dashboard-table";
import { fetchBackendJson, BackendApiError } from "@/lib/backend/client";

async function loadDashboardItems(
  authHeaders: Record<string, string>,
): Promise<{ items: DashboardFactItem[]; error: string | null }> {
  try {
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

export async function RawTab({ authHeaders }: { authHeaders: Record<string, string> }) {
  const { items, error } = await loadDashboardItems(authHeaders);

  return (
    <Section
      title="記憶の鮮度・矛盾一覧(生データ)"
      description="各記憶の最終更新日時(再確認・上書きされた時刻を含む)・確信度・重要度・矛盾検出フラグ(is_stale)・採用回数・出所(会話スレッド/作成日時)を表示します。「最終更新」は、明示的な確認履歴専用のテーブルが存在しないため、記憶が最後に書き込まれた(再主張・矛盾検出で調整された)時刻を代理指標として使用しています。"
      action={<Badge>開発者向け</Badge>}
    >
      <p className="mb-4 text-xs leading-6 text-muted-foreground">
        このタブは user_fact_items の生の行を扱う、やや専門的な運用・デバッグ向けの表示です。
        /chatの応答生成には影響しません。
      </p>
      {error ? <ErrorState message={error} /> : null}
      <MemoryDashboardTable items={items} />
    </Section>
  );
}
