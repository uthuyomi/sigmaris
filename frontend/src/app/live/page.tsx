// 役割: Sigmaris Live-3(docs/sigmaris/sigmaris_live_report.md)。Live-2の
// 最小限の確認用ページを、本格的な画面(処理の流れ・ログ・メトリクス)へ
// 発展させたもの。対象は引き続きclassify_chat_intent()のみ(依頼書の
// 範囲限定)。
//
// 【デザインシステムとの一貫性についての判断根拠】
// /growth・/timelineが使うAppShell(共通ヘッダー+下部ナビゲーション)は、
// 意図的に採用しなかった。AppShellのナビゲーションは/chat・/memory・
// /timeline・/growth・/settingsの固定5項目で構成されており(app-shell.tsx
// のnavItems)、/liveをそこへ追加するには、ナビゲーション自体の項目数
// 変更(グリッドレイアウトの再設計を含む、全ページに影響する変更)が
// 必要になる。これは「classify_chat_intent()の表示のみ」という本タスク
// の範囲を大きく超えるため、今回は見送った——代わりに、/growthページの
// ヘッダー装飾(角丸カード・アバター・タイトル)と、配色トークン
// (bg-[#212121]・text-[#ececec]・text-[#8e8ea0]・border-white/10等)を
// そのまま流用し、視覚的な一貫性のみを達成する方針にした(判断根拠を
// 報告書に明記)。ナビゲーションへの正式な導線追加は、対象処理が増え、
// Sigmaris Liveが恒久的な機能として確立した段階で改めて検討する価値が
// あると考える。

import { LiveDashboard } from "@/components/live/live-dashboard";
import { requireUser } from "@/lib/supabase/auth";

export default async function LivePage() {
  await requireUser("/live");

  return (
    <main className="min-h-screen bg-[#212121] px-3 py-4 text-[#ececec] sm:px-5 lg:px-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-4">
        <section className="rounded-3xl border border-white/10 bg-[#2f2f2f] px-5 py-6 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-[#9b59b6] text-2xl font-semibold text-white">
              Σ
            </div>
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight text-[#ececec]">Sigmaris Live</h1>
              <p className="mt-1 text-sm text-[#8e8ea0]">
                シグマリスの内部処理を、リアルタイムに可視化します。現時点では意図分類(classify_chat_intent)のみが対象です。
              </p>
            </div>
          </div>
        </section>

        <LiveDashboard />
      </div>
    </main>
  );
}
