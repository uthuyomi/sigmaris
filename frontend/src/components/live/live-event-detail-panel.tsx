"use client";

// 役割: Sigmaris Live「詳細表示、+機密情報のマスキング」タスク。ログの1行を
// クリックした際に展開される、詳細情報パネル。
//
// 【誠実さについての設計判断(依頼書3章「何も隠していないかのように
// 見せることを避ける」への対応)】
// 常に一般的な注記(「この詳細表示は…完全ではありません」)を、パネル自身に
// 表示する——これは、対象イベントで実際にマスキングが発生したかどうかに
// 関わらず、常時表示する。加えて、実際にマスキングが発生した場合のみ、
// より目立つ個別の注記(「この項目には、マスキングされた箇所が含まれて
// います」)を追加で表示する。前者だけでは「今回はマスキングされていない」
// という誤解を与えうるため、後者を、実際の発生有無に応じて出し分ける
// 二段構成にした。

import { useEffect, useState } from "react";
import type { LiveEvent } from "./types";

type DetailLookup = { eventType: "memory_search_finished" | "tool_call_finished"; key: string };

export function detailLookupFor(evt: LiveEvent): DetailLookup | null {
  if (evt.event === "memory_search_finished" && typeof evt.invocation_id === "string" && evt.invocation_id) {
    return { eventType: "memory_search_finished", key: evt.invocation_id };
  }
  if (evt.event === "tool_call_finished" && typeof evt.tool_call_id === "string" && evt.tool_call_id) {
    return { eventType: "tool_call_finished", key: evt.tool_call_id };
  }
  return null;
}

type FetchState = "loading" | "found" | "not_found" | "error";

type MemorySearchDetailItem = {
  category?: string;
  value_preview?: string;
  confidence?: number;
  similarity?: number;
};

type MemorySearchDetail = {
  items?: MemorySearchDetailItem[];
  any_masked?: boolean;
};

type ToolCallDetail = {
  tool_name?: string;
  arguments?: Record<string, unknown>;
  any_masked?: boolean;
};

function MemorySearchDetailView({ detail }: { detail: MemorySearchDetail }) {
  const items = detail.items ?? [];
  if (items.length === 0) {
    return <p className="text-sm text-[#8e8ea0]">この検索でヒットした記憶はありません。</p>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item, idx) => (
        <li key={idx} className="rounded-xl border border-white/10 bg-[#2a2a2a] p-3 text-sm">
          <p className="font-medium text-[#ececec]">{item.category || "(カテゴリ不明)"}</p>
          <p className="mt-1 text-[#c7c7d1]">{item.value_preview || "—"}</p>
          <p className="mt-1 text-xs text-[#8e8ea0]">
            confidence={typeof item.confidence === "number" ? item.confidence.toFixed(2) : "—"} ・ similarity=
            {typeof item.similarity === "number" ? item.similarity.toFixed(2) : "—"}
          </p>
        </li>
      ))}
    </ul>
  );
}

function ToolCallDetailView({ detail }: { detail: ToolCallDetail }) {
  const args = detail.arguments ?? {};
  const keys = Object.keys(args);
  return (
    <div className="text-sm">
      <p className="font-medium text-[#ececec]">{detail.tool_name || "(ツール名不明)"}</p>
      {keys.length === 0 ? (
        <p className="mt-1 text-[#8e8ea0]">引数はありません。</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-1">
          {keys.map((key) => (
            <li key={key} className="flex items-baseline gap-2 rounded-lg border border-white/10 bg-[#2a2a2a] px-2 py-1">
              <span className="font-mono text-xs text-[#8e8ea0]">{key}</span>
              <span className="text-[#c7c7d1]">{String(args[key])}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function LiveEventDetailPanel({ event }: { event: LiveEvent }) {
  const lookup = detailLookupFor(event);
  const [state, setState] = useState<FetchState>("loading");
  const [detail, setDetail] = useState<MemorySearchDetail | ToolCallDetail | null>(null);

  useEffect(() => {
    if (!lookup) return;
    let cancelled = false;
    setState("loading");
    setDetail(null);

    const url = `/api/live/detail?eventType=${encodeURIComponent(lookup.eventType)}&key=${encodeURIComponent(lookup.key)}`;
    fetch(url)
      .then((response) => response.json())
      .then((body: { ok?: boolean; found?: boolean; detail?: MemorySearchDetail | ToolCallDetail | null }) => {
        if (cancelled) return;
        if (body.ok && body.found && body.detail) {
          setDetail(body.detail);
          setState("found");
        } else {
          setState("not_found");
        }
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });

    return () => {
      cancelled = true;
    };
    // lookup is derived from `event` on every render; re-running only when
    // the identifying pair actually changes avoids refetching on unrelated
    // re-renders of the parent log.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lookup?.eventType, lookup?.key]);

  if (!lookup) {
    return <p className="text-sm text-[#8e8ea0]">この処理には、詳細表示がありません。</p>;
  }

  const anyMasked = !!detail && "any_masked" in detail && detail.any_masked === true;

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-[#212121] p-4">
      {state === "loading" && <p className="text-sm text-[#8e8ea0]">詳細情報を取得しています...</p>}
      {state === "error" && <p className="text-sm text-red-400">詳細情報の取得に失敗しました。</p>}
      {state === "not_found" && (
        <p className="text-sm text-[#8e8ea0]">
          詳細情報はまだ準備できていないか、見つかりませんでした(発行から間もない場合、少し時間をおいて再度開いてみてください)。
        </p>
      )}
      {state === "found" && detail && (
        <>
          {lookup.eventType === "memory_search_finished" ? (
            <MemorySearchDetailView detail={detail as MemorySearchDetail} />
          ) : (
            <ToolCallDetailView detail={detail as ToolCallDetail} />
          )}
          {anyMasked && (
            <p className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-200">
              この項目には、マスキングされた箇所(
              <span className="font-mono">[マスク済み]</span>
              )が含まれています。
            </p>
          )}
        </>
      )}
      <p className="text-xs text-[#5c5c66]">
        この詳細表示は、機密性の高い可能性のある情報を検出した場合にマスキングして表示します。検出は簡易的なもので、完全ではありません。
      </p>
    </div>
  );
}
