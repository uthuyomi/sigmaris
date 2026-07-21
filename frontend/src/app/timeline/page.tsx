// 役割: 旧 /timeline の URL を、統合後の「記憶」画面の「変遷」タブへ
// リダイレクトする(デザイン統一 第四段階)。
//
// 【判断根拠(独立URL→リダイレクト)】
// /memory・/timeline・/admin/memory は同じ user_fact_items を別角度で見る
// 3ページであり、Step4 で /memory を唯一の正となる記憶画面(タブ構成)へ
// 統合した。/timeline という既存URL(ブックマーク・外部リンク・第三段階まで
// のナビ導線)を壊さないよう、独立ページは廃し /memory?tab=timeline への
// 恒久リダイレクトに置き換えた。本文の描画ロジックは
// components/memory/timeline-tab.tsx へ移設済み(重複なし)。

import { redirect } from "next/navigation";

export default function TimelineRedirectPage() {
  redirect("/memory?tab=timeline");
}
