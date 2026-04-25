"use client";
// 役割: AI応答トーンの設定を表示・保存するReactクライアントコンポーネント。


import { BotIcon, CheckIcon, ChevronDownIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";
import { type AiTone } from "@/lib/profile-settings";

const toneOptions: Array<{
  value: AiTone;
  label: string;
  hint: string;
}> = [
  { value: "default", label: "標準", hint: "自然で実用的" },
  { value: "friendly", label: "柔らかめ", hint: "会話寄りで軽め" },
  { value: "concise", label: "簡潔", hint: "短く要点中心" },
  { value: "direct", label: "直接", hint: "はっきり技術寄り" },
];

type AiTonePreferencePanelProps = {
  currentTone: AiTone;
};

export function AiTonePreferencePanel({ currentTone }: AiTonePreferencePanelProps) {
  const router = useRouter();
  const [selectedTone, setSelectedTone] = useState<AiTone>(currentTone);
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const selectedOption = useMemo(
    () => toneOptions.find((option) => option.value === selectedTone) ?? toneOptions[0],
    [selectedTone],
  );

  const save = (tone: AiTone) => {
    setSelectedTone(tone);
    setOpen(false);

    if (tone === currentTone) {
      setMessage(null);
      return;
    }

    startTransition(async () => {
      setMessage(null);
      const response = await fetch("/api/settings/ai-tone", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ aiTone: tone }),
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
    <section className="rounded-[30px] border border-stone-900/10 bg-white/85 p-5 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
      <div className="flex items-start gap-4">
        <div className="inline-flex size-11 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
          <BotIcon className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold text-stone-900">AI口調</h2>
          <p className="mt-2 text-sm leading-7 text-stone-600">
            チャットでの返答の長さや距離感を調節する。
          </p>
        </div>
      </div>

      <div className="mt-5">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex w-full items-center justify-between rounded-[24px] border border-stone-900/10 bg-stone-50 px-4 py-4 text-left transition hover:bg-white"
          aria-expanded={open}
        >
          <div>
            <p className="text-sm font-semibold text-stone-900">{selectedOption.label}</p>
            <p className="mt-1 text-xs text-stone-500">{selectedOption.hint}</p>
          </div>
          <ChevronDownIcon className={`size-5 text-stone-500 transition ${open ? "rotate-180" : ""}`} />
        </button>

        {open ? (
          <div className="mt-3 space-y-2">
            {toneOptions.map((option) => {
              const active = option.value === selectedTone;

              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => save(option.value)}
                  disabled={isPending}
                  className={`flex w-full items-center justify-between rounded-[22px] border px-4 py-3 text-left transition ${
                    active
                      ? "border-stone-900 bg-stone-900 text-stone-50"
                      : "border-stone-900/10 bg-stone-50 text-stone-900 hover:bg-white"
                  }`}
                >
                  <div>
                    <p className="text-sm font-semibold">{option.label}</p>
                    <p className={`mt-1 text-xs ${active ? "text-stone-300" : "text-stone-500"}`}>
                      {option.hint}
                    </p>
                  </div>
                  {active ? <CheckIcon className="size-4" /> : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>

      {message ? <p className="mt-3 text-sm text-stone-500">{message}</p> : null}
    </section>
  );
}
