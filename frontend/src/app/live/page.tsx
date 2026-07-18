// 役割: Sigmaris Live-2(docs/sigmaris/sigmaris_live_report.md)。
// SSE配信が正しく機能しているかを確認するための、最小限のページ。
// 本格的なSigmaris Live画面(点灯・メトリクス・ログ全体設計)は、次タスク
// (Live-3以降)の範囲とし、本タスクでは実装しない。ナビゲーション
// (app-shell.tsx)にも意図的にリンクを追加していない——確認用の
// 一時的なページであり、恒久的な機能としての導線設計は範囲外と判断した。

import { LiveEventLog } from "@/components/live/live-event-log";
import { requireUser } from "@/lib/supabase/auth";

export default async function LivePage() {
  await requireUser("/live");

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-4 bg-[#171717] p-6 text-[#ececec]">
      <h1 className="text-lg font-semibold">Sigmaris Live(確認用、Live-2)</h1>
      <p className="text-sm text-[#8e8ea0]">
        classify_chat_intent()のイベント発行・SSE配信の、動作確認専用ページです。
      </p>
      <LiveEventLog />
    </main>
  );
}
