import { Assistant } from "@/app/assistant";
import { AppShell } from "@/components/app-shell";
import { requireUser } from "@/lib/supabase/auth";

export default async function ChatPage() {
  await requireUser("/chat");

  return (
    <AppShell
      title="チャットで予定調整"
      description="会話を主役にして、画像やファイルの取り込みも同じ入力欄から進める。"
      badge="OpenAI 連携"
    >
      <section className="min-h-[calc(100vh-13rem)] overflow-hidden rounded-[32px] border border-stone-900/10 bg-[linear-gradient(180deg,_rgba(35,31,32,0.98),_rgba(54,48,42,0.94))] shadow-[0_30px_90px_-50px_rgba(28,25,23,0.9)]">
        <div className="border-b border-white/10 px-5 py-5 text-stone-50 sm:px-6">
          <p className="text-xs uppercase tracking-[0.3em] text-stone-400">Assistant</p>
          <h2 className="mt-1 text-lg font-semibold">予定調整チャット</h2>
        </div>
        <div className="h-[calc(100vh-18rem)] min-h-[38rem]">
          <Assistant />
        </div>
      </section>
    </AppShell>
  );
}
