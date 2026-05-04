"use client";
// 役割: 保存済み地点の一覧表示と編集操作を行うReactクライアントコンポーネント。


import { HomeIcon, MapPinPlusIcon, SaveIcon, Trash2Icon } from "lucide-react";
import { useEffect, useState, useTransition } from "react";

type SavedLocation = {
  id: string;
  label: string;
  address: string;
  locationType: "home" | "work" | "custom";
  isDefaultDeparture: boolean;
};

export function SavedLocationsPanel() {
  const [homeAddress, setHomeAddress] = useState("");
  const [locations, setLocations] = useState<SavedLocation[]>([]);
  const [label, setLabel] = useState("");
  const [address, setAddress] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const load = async () => {
    const response = await fetch("/api/settings/locations", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    setHomeAddress(data.homeAddress ?? "");
    setLocations(data.locations ?? []);
  };

  useEffect(() => {
    let ignore = false;

    fetch("/api/settings/locations", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!data || ignore) return;
        startTransition(() => {
          setHomeAddress(data.homeAddress ?? "");
          setLocations(data.locations ?? []);
        });
      })
      .catch(() => undefined);

    return () => {
      ignore = true;
    };
  }, []);

  const saveHome = () => {
    startTransition(async () => {
      const response = await fetch("/api/settings/locations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ homeAddress }),
      });
      if (!response.ok) return;
      setMessage("Home updated");
      await load();
    });
  };

  const addLocation = () => {
    if (!label.trim() || !address.trim()) return;
    startTransition(async () => {
      const response = await fetch("/api/settings/locations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label,
          address,
          locationType: "custom",
        }),
      });
      if (!response.ok) return;
      setLabel("");
      setAddress("");
      setMessage("Location saved");
      await load();
    });
  };

  const removeLocation = (id: string) => {
    startTransition(async () => {
      const response = await fetch(`/api/settings/locations/${id}`, {
        method: "DELETE",
      });
      if (!response.ok) return;
      setMessage("Location removed");
      await load();
    });
  };

  return (
    <section className="rounded-2xl border border-stone-900/10 bg-white p-5 shadow-sm dark:border-white/10 dark:bg-[#2f2f2f]">
      <div className="flex items-start gap-3">
        <div className="settings-item-icon inline-flex size-11 items-center justify-center rounded-xl">
          <HomeIcon className="size-5" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-stone-900">出発地点</h2>
          <p className="mt-2 text-sm leading-7 text-stone-600">
            自宅やよく使う場所を保存して、移動予定の出発地に使う。
          </p>
        </div>
      </div>

      <div className="mt-5 space-y-3">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-stone-500">Home</p>
        <input
          value={homeAddress}
          onChange={(event) => setHomeAddress(event.target.value)}
          placeholder="自宅住所"
          className="w-full rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-3 text-sm outline-none dark:border-white/10 dark:bg-white/6 dark:text-stone-100"
        />
        <button
          type="button"
          onClick={saveHome}
          disabled={isPending}
          className="inline-flex size-10 items-center justify-center rounded-full bg-stone-900 text-stone-50 disabled:opacity-60 dark:bg-white dark:text-stone-950"
          aria-label="自宅を保存"
        >
          <SaveIcon className="size-4" />
        </button>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-[0.8fr_1.4fr_auto]">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-stone-500 sm:col-span-3">
          Saved places
        </p>
        <input
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="地点名"
          className="rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-3 text-sm outline-none dark:border-white/10 dark:bg-white/6 dark:text-stone-100"
        />
        <input
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          placeholder="住所"
          className="rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-3 text-sm outline-none dark:border-white/10 dark:bg-white/6 dark:text-stone-100"
        />
        <button
          type="button"
          onClick={addLocation}
          disabled={isPending}
          className="inline-flex size-12 items-center justify-center rounded-full bg-stone-900 text-stone-50 disabled:opacity-60 dark:bg-white dark:text-stone-950"
          aria-label="地点を追加"
        >
          <MapPinPlusIcon className="size-4" />
        </button>
      </div>

      <div className="mt-5 space-y-2">
        {locations.map((location) => (
          <div
            key={location.id}
            className="flex items-center justify-between rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-3 dark:border-white/10 dark:bg-white/6"
          >
            <div>
              <p className="text-sm font-semibold text-stone-900">{location.label}</p>
              <p className="mt-1 text-xs text-stone-500">{location.address}</p>
            </div>
            <button
              type="button"
              onClick={() => removeLocation(location.id)}
              className="inline-flex size-9 items-center justify-center rounded-full bg-stone-900/5 text-stone-700 dark:bg-white/8 dark:text-stone-300"
              aria-label="地点を削除"
            >
              <Trash2Icon className="size-4" />
            </button>
          </div>
        ))}
      </div>

      {message ? <p className="mt-3 text-sm text-stone-500">{message}</p> : null}
    </section>
  );
}
