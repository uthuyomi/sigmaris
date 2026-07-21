// 役割: 旧 /admin/memory の URL を、統合後の「記憶」画面の「生データ
// (開発者向け)」タブへリダイレクトする(デザイン統一 第四段階)。
//
// 【判断根拠】
// /admin/memory(B5・記憶の鮮度/矛盾ダッシュボード)は、/memory・/timeline と
// 同じ user_fact_items を"生データ"の角度から見る開発者向けページだった。
// Step4 で /memory のタブへ統合したため、独立ページは廃し
// /memory?tab=raw への恒久リダイレクトに置き換えた。"開発者向けの生データ
// 表示"という性質は、統合先タブ(生データ(開発者向け)・"やや専門的"注記)で
// 保持している(components/memory/raw-tab.tsx)。従来この URL は意図的な
// 隠しページで、ナビからは到達できなかった点も統合後のタブで踏襲される
// (タブ自体は /memory に表示されるが、内容の専門性は明示)。

import { redirect } from "next/navigation";

export default function AdminMemoryRedirectPage() {
  redirect("/memory?tab=raw");
}
