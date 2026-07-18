"use client";

// 役割: Sigmaris Live-2(docs/sigmaris/sigmaris_live_report.md)。
// 「イベントが正しく配信されているか」を確認するための、最小限の
// テキストログ表示。本格的なSigmaris Live画面(点灯・メトリクス等)は、
// 本タスクでは実装しない(依頼書「最小限の簡易な表示で十分」)。

import { useEffect, useRef, useState } from "react";

type LiveEvent = {
  event: string;
  invocation_id: string;
  timestamp: number;
  [key: string]: unknown;
};

type LogLine = {
  id: number;
  receivedAt: string;
  raw: LiveEvent | { error: string };
};

export function LiveEventLog() {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [status, setStatus] = useState<"connecting" | "open" | "error">("connecting");
  const nextId = useRef(0);

  useEffect(() => {
    const source = new EventSource("/api/live/stream");

    source.onopen = () => setStatus("open");
    source.onerror = () => setStatus("error");
    source.onmessage = (message) => {
      let parsed: LiveEvent | { error: string };
      try {
        parsed = JSON.parse(message.data) as LiveEvent;
      } catch {
        parsed = { error: `JSON解析に失敗しました: ${message.data}` };
      }
      setLines((prev) => [
        ...prev.slice(-199), // 直近200件のみ保持(確認用途のため無制限には貯めない)
        { id: nextId.current++, receivedAt: new Date().toLocaleTimeString(), raw: parsed },
      ]);
    };

    return () => source.close();
  }, []);

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-[#8e8ea0]">
        接続状態:{" "}
        <span
          className={
            status === "open"
              ? "text-emerald-400"
              : status === "error"
                ? "text-red-400"
                : "text-[#8e8ea0]"
          }
        >
          {status === "open" ? "接続中" : status === "error" ? "エラー" : "接続試行中..."}
        </span>
      </p>
      <p className="text-xs text-[#8e8ea0]">
        チャット画面(/chat)で会話すると、classify_chat_intent()の開始・終了イベントがここに表示されます。
      </p>
      <div className="max-h-[70vh] overflow-y-auto rounded-lg border border-white/10 bg-black/40 p-3 font-mono text-xs">
        {lines.length === 0 && <p className="text-[#8e8ea0]">まだイベントを受信していません。</p>}
        {lines.map((line) => (
          <div key={line.id} className="border-b border-white/5 py-1 text-[#ececec]">
            [{line.receivedAt}] {JSON.stringify(line.raw)}
          </div>
        ))}
      </div>
    </div>
  );
}
