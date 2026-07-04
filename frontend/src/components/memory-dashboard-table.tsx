"use client";
// 役割: Phase B5 記憶ダッシュボード(開発者向け)の一覧テーブル。フィルタ・
// ソートはこのコンポーネント内でクライアント側完結させ、追加のAPI呼び出しは
// 発生させない(単一ユーザー向けの少件数データのため)。

import { useMemo, useState } from "react";

export type DashboardFactItem = {
  id?: string;
  category?: string | null;
  key?: string | null;
  value?: unknown;
  confidence?: number | string | null;
  importance_score?: number | string | null;
  is_stale?: boolean | null;
  adoption_count?: number | null;
  source?: string | null;
  thread_id?: string | null;
  invocation_id?: string | null;
  source_experience_ids?: string[] | null;
  created_at?: string | null;
  updated_at?: string | null;
};

type SortKey = "updated_at" | "importance_score" | "confidence" | "category";

function toNumber(value: unknown, fallback = 0): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未設定";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
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

function shortId(value?: string | null): string {
  if (!value) return "―";
  return value.length > 8 ? `${value.slice(0, 8)}…` : value;
}

export function MemoryDashboardTable({ items }: { items: DashboardFactItem[] }) {
  const [staleOnly, setStaleOnly] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("updated_at");
  const [sortAsc, setSortAsc] = useState(true);

  const visible = useMemo(() => {
    const filtered = staleOnly ? items.filter((item) => item.is_stale) : items;
    const sorted = [...filtered].sort((a, b) => {
      let diff = 0;
      if (sortKey === "category") {
        diff = (a.category ?? "").localeCompare(b.category ?? "");
      } else if (sortKey === "updated_at") {
        diff = new Date(a.updated_at ?? 0).getTime() - new Date(b.updated_at ?? 0).getTime();
      } else {
        diff = toNumber(a[sortKey]) - toNumber(b[sortKey]);
      }
      return sortAsc ? diff : -diff;
    });
    return sorted;
  }, [items, staleOnly, sortKey, sortAsc]);

  const staleCount = items.filter((item) => item.is_stale).length;

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortAsc((value) => !value);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  }

  function headerButton(key: SortKey, label: string) {
    const active = key === sortKey;
    return (
      <button
        type="button"
        onClick={() => toggleSort(key)}
        className={`inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide ${
          active ? "text-[#ececec]" : "text-[#8e8ea0]"
        }`}
      >
        {label}
        {active ? <span>{sortAsc ? "▲" : "▼"}</span> : null}
      </button>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm text-[#d8d8de]">
          <input
            type="checkbox"
            checked={staleOnly}
            onChange={(event) => setStaleOnly(event.target.checked)}
            className="size-4 rounded border-white/20 bg-transparent"
          />
          矛盾フラグ(is_stale)のみ表示
        </label>
        <span className="text-xs text-[#8e8ea0]">
          全{items.length}件中、矛盾フラグあり{staleCount}件 / 表示中{visible.length}件
        </span>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-white/10">
        <table className="w-full min-w-[900px] border-collapse text-left text-sm">
          <thead className="bg-white/[0.04]">
            <tr>
              <th className="px-3 py-2">{headerButton("category", "カテゴリ / キー")}</th>
              <th className="px-3 py-2">値</th>
              <th className="px-3 py-2">{headerButton("confidence", "確信度")}</th>
              <th className="px-3 py-2">{headerButton("importance_score", "重要度")}</th>
              <th className="px-3 py-2">矛盾</th>
              <th className="px-3 py-2">採用回数</th>
              <th className="px-3 py-2">出所</th>
              <th className="px-3 py-2">{headerButton("updated_at", "最終更新")}</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((item, index) => (
              <tr
                key={item.id ?? `${item.category}-${item.key}-${index}`}
                className={`border-t border-white/5 ${item.is_stale ? "bg-red-500/10" : ""}`}
              >
                <td className="px-3 py-2 align-top">
                  <div className="font-semibold text-[#ececec]">{item.category || "―"}</div>
                  <div className="text-xs text-[#8e8ea0]">{item.key || "―"}</div>
                </td>
                <td className="max-w-[240px] px-3 py-2 align-top">
                  <span className="line-clamp-3 whitespace-pre-wrap break-words text-[#d8d8de]">
                    {formatValue(item.value)}
                  </span>
                </td>
                <td className="px-3 py-2 align-top tabular-nums">
                  {toNumber(item.confidence, 1).toFixed(2)}
                </td>
                <td className="px-3 py-2 align-top tabular-nums">
                  {toNumber(item.importance_score, 0.5).toFixed(2)}
                </td>
                <td className="px-3 py-2 align-top">
                  {item.is_stale ? (
                    <span className="inline-flex items-center rounded-full border border-red-400/30 bg-red-500/15 px-2.5 py-1 text-xs font-medium text-red-100">
                      矛盾あり
                    </span>
                  ) : (
                    <span className="text-xs text-[#8e8ea0]">―</span>
                  )}
                </td>
                <td className="px-3 py-2 align-top tabular-nums">{item.adoption_count ?? 0}</td>
                <td className="px-3 py-2 align-top">
                  <div className="text-xs text-[#d8d8de]">{item.source || "unknown"}</div>
                  <div className="text-xs text-[#8e8ea0]">
                    thread: {shortId(item.thread_id)}
                  </div>
                  <div className="text-xs text-[#8e8ea0]">
                    作成: {formatDate(item.created_at)}
                  </div>
                </td>
                <td className="px-3 py-2 align-top text-xs text-[#d8d8de]">
                  {formatDate(item.updated_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-[#8e8ea0]">
            表示する記憶がありません。
          </div>
        ) : null}
      </div>
    </div>
  );
}
