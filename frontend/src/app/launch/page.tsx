import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/supabase/auth";

export default async function LaunchPage() {
  const user = await getCurrentUser();

  if (user) {
    redirect("/chat");
  }

  redirect("/login?next=/chat");
}
