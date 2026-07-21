// 役割: Sigmaris Live-3(docs/sigmaris/sigmaris_live_report.md)。Live-2の
// 最小限の確認用ページを、本格的な画面(処理の流れ・ログ・メトリクス)へ
// 発展させたもの。対象は引き続きclassify_chat_intent()のみ(依頼書の
// 範囲限定)。
//
// 【ナビゲーション上の位置づけ: 意図的な"隠しページ"】
// デザイン統一 第三段階(ナビ一本化)の方針として、/live は AppShell の
// navItems にも SigmarisSidebar にも追加しない。/admin/memory と同様、
// URL直打ちでのみ到達する意図的な隠しページである(main nav には載せない)。
// 理由: Sigmaris Live は将来 Step 5 で「チャット画面のサイドバーへ統合」
// する計画が既にあり、独立ページとして恒久的なナビ導線を張るより、その
// 統合まで隠しページに留める方が、後戻り(ナビからの再削除)を避けられる
// と判断した(判断根拠、docs/sigmaris/frontend_design_unification_report.md
// 第三段階に記載)。デモ用途(?demo=1)・内部確認用途で直接URLアクセスする
// 分には現状のままで支障ない。
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
import { PageHero } from "@/components/shared";
import { requireUser } from "@/lib/supabase/auth";

// Sigmaris Live-7(デモモード): ?demo=1 で、実際のSSE接続の代わりに、
// 個人情報を一切含まない架空のシナリオを再生する(X発信・動画撮影用)。
// サーバーコンポーネント側でsearchParamsを読み、真偽値へ変換した上で
// LiveDashboard(クライアントコンポーネント)へpropsとして渡す設計にした
// ——LiveDashboard側でuseSearchParams()を直接呼ぶ選択肢も検討したが、
// App RouterでuseSearchParams()を使うクライアントコンポーネントは
// Suspense境界で包む必要があり、既存のページ構成に余計な変更が
// 必要になる。searchParamsは、このページ(サーバーコンポーネント)が
// 既に受け取れる情報のため、propsとして1回渡すだけで済む、こちらの
// 方法を選んだ(判断根拠)。
type LivePageProps = {
  searchParams?: Promise<{ demo?: string }>;
};

export default async function LivePage({ searchParams }: LivePageProps) {
  await requireUser("/live");
  const params = searchParams ? await searchParams : undefined;
  const demoMode = params?.demo === "1" || params?.demo === "true";

  return (
    <main className="min-h-screen bg-background px-3 py-4 text-foreground sm:px-5 lg:px-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-5 pb-4">
        <PageHero
          title="Sigmaris Live"
          description="シグマリスの内部処理を、リアルタイムに可視化します。現時点では意図分類(classify_chat_intent)のみが対象です。"
        />

        <LiveDashboard demoMode={demoMode} />
      </div>
    </main>
  );
}
