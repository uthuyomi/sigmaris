"use client";
// 役割: 到着余裕時間の設定を表示・保存するReactクライアントコンポーネント。


import { Clock3Icon, SaveIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

type ArrivalLeadMinutesPanelProps = {
  currentMinutes: number;
};

export function ArrivalLeadMinutesPanel({ currentMinutes }: ArrivalLeadMinutesPanelProps) {
  const router = useRouter();
  const [minutes, setMinutes] = useState(currentMinutes);
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const save = () => {
    startTransition(async () => {
      setMessage(null);
      const response = await fetch("/api/settings/arrival-lead-minutes", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ minutes }),
      });

      if (!response.ok) {
        setMessage("Failed");
        return;
      }

      setMessage("Saved");
      router.refresh();
    });
  };

  return (
    <section className="rounded-2xl border border-stone-900/10 bg-white p-5 shadow-sm dark:border-white/10 dark:bg-[#2f2f2f]">
      <div className="flex items-start gap-4">
        <div className="inline-flex size-11 items-center justify-center rounded-xl bg-stone-900 text-stone-50 dark:bg-white dark:text-stone-950">
          <Clock3Icon className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold text-stone-900">到着余裕時間</h2>
          <p className="mt-2 text-sm leading-7 text-stone-600">
            予定開始の何分前に着くかを指定する。移動予定の出発時刻に反映される。
          </p>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <input
          type="number"
          min={0}
          max={180}
          step={1}
          value={minutes}
          onChange={(event) => setMinutes(Number(event.target.value))}
          className="w-32 rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-3 text-sm outline-none dark:border-white/10 dark:bg-white/6 dark:text-stone-100"
        />
        <span className="text-sm text-stone-500">分前には到着</span>
        <button
          type="button"
          onClick={save}
          disabled={isPending}
          className="inline-flex size-10 items-center justify-center rounded-full bg-stone-900 text-stone-50 disabled:opacity-60 dark:bg-white dark:text-stone-950"
          aria-label="保存"
        >
          <SaveIcon className="size-4" />
        </button>
      </div>

      {message ? <p className="mt-3 text-sm text-stone-500">{message}</p> : null}
    </section>
  );
}
