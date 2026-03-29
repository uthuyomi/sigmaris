import { Assistant } from "@/app/assistant";
import { AppShell } from "@/components/app-shell";
import { ImportEntryPanel } from "@/components/import-entry-panel";
import { requireUser } from "@/lib/supabase/auth";

export default async function ChatPage() {
  await requireUser("/chat");

  return (
    <AppShell
      title="チャットで予定調整"
      description="会話しながら予定候補を組み、画像やスプレッドシート URL もここから AI に読み込ませる。"
      badge="OpenAI 連携"
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="min-h-[42rem] overflow-hidden rounded-[32px] border border-stone-900/10 bg-[linear-gradient(180deg,_rgba(35,31,32,0.96),_rgba(54,48,42,0.92))] shadow-[0_30px_90px_-50px_rgba(28,25,23,0.9)]">
          <div className="border-b border-white/10 px-5 py-5 text-stone-50">
            <p className="text-xs uppercase tracking-[0.3em] text-stone-400">Assistant</p>
            <h2 className="mt-1 text-lg font-semibold">予定調整チャット</h2>
          </div>
          <div className="h-[calc(42rem-5.5rem)] min-h-0">
            <Assistant />
          </div>
        </section>

        <ImportEntryPanel />
      </div>
    </AppShell>
  );
}
