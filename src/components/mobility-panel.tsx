"use client";

import { getDictionary, type AppLocale } from "@/lib/i18n";
import type { EventItem } from "@/lib/mock-schedule";
import { AlertTriangleIcon, CheckIcon, MapPinnedIcon, PlusCircleIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

type MobilityPanelProps = {
  locale: AppLocale;
  selectedEvent?: EventItem;
};

type SavedLocation = {
  id: string;
  label: string;
  address: string;
  locationType: "home" | "work" | "custom";
  isDefaultDeparture: boolean;
};

type ScheduleResponse = {
  routePlan: {
    mode: "transit" | "driving" | "walking";
    originLabel: string;
    destinationLabel: string;
    recommendedDepartureTime?: string;
    estimatedArrivalTime?: string;
    durationText?: string;
    steps: Array<{
      instruction: string;
      lineName?: string;
      departureTime?: string;
      arrivalTime?: string;
    }>;
  };
  travelEvent: {
    title: string;
    description?: string;
    startsAt: string;
    endsAt: string;
  };
  warnings: Array<{
    id: string;
    title: string;
    startsAt: string;
    endsAt: string;
  }>;
  willSyncToGoogle?: boolean;
  savedToGoogle?: boolean;
};

const readJsonSafely = async (response: Response) => {
  const text = await response.text();
  if (!text.trim()) {
    return {};
  }

  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new Error("The route service returned an invalid response.");
  }
};

export function MobilityPanel({ locale, selectedEvent }: MobilityPanelProps) {
  const dict = getDictionary(locale);
  const [travelMode, setTravelMode] = useState<"transit" | "driving" | "walking">("transit");
  const [originType, setOriginType] = useState<"home" | "current" | "saved" | "custom">("home");
  const [origin, setOrigin] = useState("");
  const [savedLocations, setSavedLocations] = useState<SavedLocation[]>([]);
  const [homeAddress, setHomeAddress] = useState("");
  const [selectedSavedId, setSelectedSavedId] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [preview, setPreview] = useState<ScheduleResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const selectedSaved = useMemo(
    () => savedLocations.find((location) => location.id === selectedSavedId),
    [savedLocations, selectedSavedId],
  );

  useEffect(() => {
    const load = async () => {
      const response = await fetch("/api/settings/locations", { cache: "no-store" });
      if (!response.ok) return;
      const data = await response.json();
      const locations = (data.locations ?? []) as SavedLocation[];
      setSavedLocations(locations);
      setHomeAddress(data.homeAddress ?? "");
      const defaultLocation = locations.find((location) => location.isDefaultDeparture) ?? locations[0];
      if (defaultLocation) {
        setSelectedSavedId(defaultLocation.id);
      }
    };

    void load();
  }, []);

  useEffect(() => {
    if (originType === "home") {
      setOrigin(homeAddress);
    } else if (originType === "saved" && selectedSaved) {
      setOrigin(selectedSaved.address);
    }
  }, [originType, homeAddress, selectedSaved]);

  const resolveCurrentLocation = () =>
    new Promise<{ origin: string; label: string }>((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error("Geolocation unavailable"));
        return;
      }

      navigator.geolocation.getCurrentPosition(
        (position) => {
          resolve({
            origin: `${position.coords.latitude},${position.coords.longitude}`,
            label: "Current location",
          });
        },
        () => reject(new Error("Geolocation denied")),
      );
    });

  const buildOriginInput = async () => {
    if (originType === "current") {
      return resolveCurrentLocation();
    }

    if (originType === "saved" && selectedSaved) {
      return { origin: selectedSaved.address, label: selectedSaved.label };
    }

    return {
      origin,
      label: originType === "home" ? "Home" : "Custom",
    };
  };

  const runSchedule = async (confirm = false, force = false) => {
    if (!selectedEvent?.location) {
      setStatus("No destination on this event.");
      return;
    }

    setLoading(true);
    setStatus(null);

    try {
      const originInput = await buildOriginInput();
      const response = await fetch("/api/mobility/schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          eventId: selectedEvent.id,
          originType,
          origin: originInput.origin,
          originLabel: originInput.label,
          travelMode,
          confirm,
          force,
        }),
      });

      const data = (await readJsonSafely(response)) as Partial<ScheduleResponse> & {
        error?: string;
      };
      if (response.status === 409) {
        setPreview(data as ScheduleResponse);
        setStatus("Conflicts found. Review before saving.");
        return;
      }
      if (!response.ok) {
        throw new Error(data.error ?? "Mobility scheduling failed");
      }

      setPreview(data as ScheduleResponse);
      setStatus(confirm ? "Travel block saved." : null);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Mobility scheduling failed";
      setStatus(
        message.includes("No public transit route was found")
          ? "その到着時刻では公共交通ルートが見つからなかったよ。時間をずらすか、Car / Walk も試してみてね。"
          : message,
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="rounded-[28px] border border-stone-900/10 bg-white p-4">
      <div className="flex items-start gap-3">
        <div className="inline-flex size-11 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
          <MapPinnedIcon className="size-5" />
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Mobility</p>
          <h3 className="mt-2 text-base font-semibold text-stone-900">
            {selectedEvent?.location ?? dict.common.unavailable}
          </h3>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <div className="flex flex-wrap gap-2">
          {(["home", "current", "saved", "custom"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setOriginType(value)}
              className={`rounded-full px-3 py-2 text-xs font-medium ${
                originType === value
                  ? "bg-stone-900 text-stone-50"
                  : "bg-stone-100 text-stone-700"
              }`}
            >
              {value === "home"
                ? "Home"
                : value === "current"
                  ? "GPS"
                  : value === "saved"
                    ? "Saved"
                    : "Custom"}
            </button>
          ))}
        </div>

        {originType === "saved" ? (
          <select
            value={selectedSavedId}
            onChange={(event) => setSelectedSavedId(event.target.value)}
            className="w-full rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-3 text-sm outline-none"
          >
            <option value="">Select saved location</option>
            {savedLocations.map((location) => (
              <option key={location.id} value={location.id}>
                {location.label}
              </option>
            ))}
          </select>
        ) : originType !== "current" ? (
          <input
            value={origin}
            onChange={(event) => setOrigin(event.target.value)}
            placeholder={originType === "home" ? "Home address" : "Origin"}
            className="w-full rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-3 text-sm outline-none"
          />
        ) : null}

        <div className="flex flex-wrap gap-2">
          {(["transit", "driving", "walking"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setTravelMode(value)}
              className={`rounded-full px-3 py-2 text-xs font-medium ${
                travelMode === value
                  ? "bg-[#e76f51] text-white"
                  : "bg-stone-100 text-stone-700"
              }`}
            >
              {value === "transit" ? "Transit" : value === "driving" ? "Car" : "Walk"}
            </button>
          ))}
        </div>

        <button
          type="button"
          disabled={loading || !selectedEvent?.location}
          onClick={() => runSchedule(false)}
          className="w-full rounded-full bg-stone-900 px-4 py-3 text-sm font-semibold text-stone-50 transition hover:bg-stone-800 disabled:opacity-50"
        >
          {loading ? dict.common.loading : "Check route and travel block"}
        </button>
      </div>

      {preview ? (
        <div className="mt-4 space-y-3 rounded-[24px] border border-stone-900/10 bg-stone-50 p-4">
          <div>
            <p className="text-sm font-semibold text-stone-900">
              {preview.routePlan.recommendedDepartureTime ?? "--:--"} →{" "}
              {preview.routePlan.estimatedArrivalTime ?? "--:--"}
            </p>
            <p className="mt-1 text-sm text-stone-600">{preview.routePlan.durationText ?? "-"}</p>
          </div>

          <div className="rounded-2xl border border-stone-900/8 bg-white px-3 py-3">
            <p className="text-xs uppercase tracking-[0.18em] text-stone-500">Travel block</p>
            <p className="mt-2 text-sm font-semibold text-stone-900">{preview.travelEvent.title}</p>
            <p className="mt-1 text-xs text-stone-500">
              {preview.travelEvent.startsAt} → {preview.travelEvent.endsAt}
            </p>
          </div>

          {preview.warnings.length ? (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-3 text-amber-900">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <AlertTriangleIcon className="size-4" />
                Conflicts detected
              </div>
              <div className="mt-2 space-y-2 text-xs leading-6">
                {preview.warnings.map((warning) => (
                  <div key={warning.id}>
                    {warning.title} / {warning.startsAt} → {warning.endsAt}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="space-y-2">
            {preview.routePlan.steps.slice(0, 4).map((step, index) => (
              <div
                key={`${step.instruction}-${index}`}
                className="rounded-2xl border border-stone-900/8 bg-white px-3 py-3"
              >
                <p className="text-sm font-medium text-stone-900">{step.instruction}</p>
                {step.lineName ? (
                  <p className="mt-1 text-xs text-stone-600">
                    {step.lineName}
                    {step.departureTime ? ` / ${step.departureTime}` : ""}
                    {step.arrivalTime ? ` → ${step.arrivalTime}` : ""}
                  </p>
                ) : null}
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => runSchedule(true, false)}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-full bg-stone-900 px-4 py-2 text-sm font-semibold text-stone-50"
            >
              <CheckIcon className="size-4" />
              Confirm and save
            </button>
            {preview.warnings.length ? (
              <button
                type="button"
                onClick={() => runSchedule(true, true)}
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-full bg-amber-600 px-4 py-2 text-sm font-semibold text-white"
              >
                <PlusCircleIcon className="size-4" />
                Save anyway
              </button>
            ) : null}
          </div>

          {preview.willSyncToGoogle ? (
            <p className="text-xs text-stone-500">Google Calendar sync is enabled for this save.</p>
          ) : null}
          {preview.savedToGoogle ? (
            <p className="text-xs text-stone-500">Saved to Google Calendar too.</p>
          ) : null}
        </div>
      ) : null}

      {status ? <p className="mt-4 text-sm leading-7 text-stone-600">{status}</p> : null}
    </section>
  );
}
