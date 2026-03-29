import { redirect } from "next/navigation";
import { requireUser } from "@/lib/supabase/auth";

export default async function AppHomePage() {
  await requireUser("/app");
  redirect("/calendar");
}
