"use client";
// 役割: 優先移動手段の設定を表示・保存するReactクライアントコンポーネント。


import { BikeIcon, CarIcon, CheckIcon, ChevronDownIcon, FootprintsIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";
import { type PreferredTravelMode } from "@/lib/profile-settings";

const travelModeOptions: Array<{
  value: PreferredTravelMode;
  label: string;
  hint: string;
  icon: typeof CarIcon;
}> = [
  { value: "car", label: "車", hint: "車でルート検索", icon: CarIcon },
  { value: "bicycle", label: "自転車", hint: "自転車でルート検索", icon: BikeIcon },
  { value: "walk", label: "徒歩", hint: "徒歩でルート検索", icon: FootprintsIcon },
];

type PreferredTravelModePanelProps = {
  currentTravelMode: PreferredTravelMode;
};

export function PreferredTravelModePanel({
  currentTravelMode,
}: PreferredTravelModePanelProps) {
  const router = useRouter();
  const [selectedTravelMode, setSelectedTravelMode] =
    useState<PreferredTravelMode>(currentTravelMode);
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const selectedOption = useMemo(
    () =>
      travelModeOptions.find((option) => option.value === selectedTravelMode) ??
      travelModeOptions[0],
    [selectedTravelMode],
  );

  const save = (travelMode: PreferredTravelMode) => {
    setSelectedTravelMode(travelMode);
    setOpen(false);

    if (travelMode === currentTravelMode) {
      setMessage(null);
      return;
    }

    startTransition(async () => {
      setMessage(null);
      const response = await fetch("/api/settings/travel-mode", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ travelMode }),
      });

      if (!response.ok) {
        setMessage("Failed");
        return;
      }

      setMessage("Saved");
      router.refresh();
    });
  };

  const SelectedIcon = selectedOption.icon;

  return (
    <section className="rounded-[30px] border border-stone-900/10 bg-white/85 p-5 shadow-[0_30px_90px_-55px_rgba(41,37,36,0.75)] backdrop-blur">
      <div className="flex items-start gap-4">
        <div className="inline-flex size-11 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
          <SelectedIcon className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold text-stone-900">移動手段</h2>
          <p className="mt-2 text-sm leading-7 text-stone-600">
            移動予定を作るとき、最初に使う移動手段を選ぶ。
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
          <div className="flex items-center gap-3">
            <div className="inline-flex size-10 items-center justify-center rounded-2xl bg-white text-stone-700">
              <SelectedIcon className="size-4" />
            </div>
            <div>
              <p className="text-sm font-semibold text-stone-900">{selectedOption.label}</p>
              <p className="mt-1 text-xs text-stone-500">{selectedOption.hint}</p>
            </div>
          </div>
          <ChevronDownIcon className={`size-5 text-stone-500 transition ${open ? "rotate-180" : ""}`} />
        </button>

        {open ? (
          <div className="mt-3 space-y-2">
            {travelModeOptions.map((option) => {
              const active = option.value === selectedTravelMode;
              const Icon = option.icon;

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
                  <div className="flex items-center gap-3">
                    <div className={`inline-flex size-10 items-center justify-center rounded-2xl ${active ? "bg-white/10 text-stone-50" : "bg-white text-stone-700"}`}>
                      <Icon className="size-4" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold">{option.label}</p>
                      <p className={`mt-1 text-xs ${active ? "text-stone-300" : "text-stone-500"}`}>
                        {option.hint}
                      </p>
                    </div>
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
