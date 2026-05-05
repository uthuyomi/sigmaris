// 役割: ログイン後のアプリホーム画面を構成するNext.jsページ。

import { redirect } from "next/navigation";

export default async function AppHomePage() {
  redirect("/calendar");
}
