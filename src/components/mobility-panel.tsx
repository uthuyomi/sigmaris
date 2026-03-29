"use client";

import { getDictionary, type AppLocale } from "@/lib/i18n";
import type { EventItem } from "@/lib/mock-schedule";
import { toIsoDateTime } from "@/lib/mock-schedule";
import { useState } from "react";

type MobilityPanelProps = {
  locale: AppLocale;
  selectedEvent?: EventItem;
};

type PlanResponse = {
  plan: {
    mode: "transit" | "driving" | "walking";
    originLabel: string;
    destinationLabel: string;
    recommendedDepartureTime?: string;
    estimatedArrivalTime?: string;
    durationText?: string;
    steps: Array<{
      instruction: string;
      travelMode: string;
      lineName?: string;
      departureStop?: string;
      arrivalStop?: string;
      departureTime?: string;
      arrivalTime?: string;
    }>;
  };
};

export function MobilityPanel({ locale, selectedEvent }: MobilityPanelProps) {
  const dict = getDictionary(locale);
  const [travelMode, setTravelMode] = useState<"transit" | "driving" | "walking">(
    "transit",
  );
  const [originType, setOriginType] = useState<"home" | "current" | "custom">("home");
  const [origin, setOrigin] = useState(process.env.NEXT_PUBLIC_HOME_ADDRESS ?? "");
  const [status, setStatus] = useState<string | null>(null);
  const [plan, setPlan] = useState<PlanResponse["plan"] | null>(null);
  const [loading, setLoading] = useState(false);

  const resolveCurrentLocation = () =>
    new Promise<string>((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error("Geolocation unavailable"));
        return;
      }

      navigator.geolocation.getCurrentPosition(
        (position) => {
          resolve(`${position.coords.latitude},${position.coords.longitude}`);
        },
        () => reject(new Error("Geolocation denied")),
      );
    });

  const fetchPlan = async () => {
    if (!selectedEvent?.location) {
      setStatus("No location");
      return;
    }

    setLoading(true);
    setStatus(null);

    try {
      const resolvedOrigin =
        originType === "current" ? await resolveCurrentLocation() : origin;

      const response = await fetch("/api/mobility/plan", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          originType,
          origin: resolvedOrigin,
          destination: selectedEvent.location,
          travelMode,
          arrivalTimeIso: toIsoDateTime(selectedEvent.date, selectedEvent.startMinutes),
          departureTimeIso: toIsoDateTime(selectedEvent.date, selectedEvent.startMinutes - 60),
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error ?? "Route planning failed");
      }

      setPlan(data.plan);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Route planning failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="rounded-[28px] border border-stone-900/10 bg-white p-4">
      <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Route</p>
      <h3 className="mt-2 text-base font-semibold text-stone-900">
        {selectedEvent?.location ?? dict.common.unavailable}
      </h3>

      <div className="mt-4 space-y-3">
        <div className="flex flex-wrap gap-2">
          {(["home", "current", "custom"] as const).map((value) => (
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
              {value === "home" ? "Home" : value === "current" ? "GPS" : "Edit"}
            </button>
          ))}
        </div>

        {originType !== "current" ? (
          <input
            value={origin}
            onChange={(event) => setOrigin(event.target.value)}
            placeholder={originType === "home" ? "Home" : "Origin"}
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
              {value === "transit" ? "Train" : value === "driving" ? "Car" : "Walk"}
            </button>
          ))}
        </div>

        <button
          type="button"
          disabled={loading || !selectedEvent?.location}
          onClick={fetchPlan}
          className="w-full rounded-full bg-stone-900 px-4 py-3 text-sm font-semibold text-stone-50 transition hover:bg-stone-800 disabled:opacity-50"
        >
          {loading ? dict.common.loading : dict.common.syncNow}
        </button>
      </div>

      {plan ? (
        <div className="mt-4 rounded-[24px] border border-stone-900/10 bg-stone-50 p-4">
          <p className="text-sm font-semibold text-stone-900">
            {plan.recommendedDepartureTime ?? "--:--"}
          </p>
          <p className="mt-1 text-sm text-stone-600">
            {plan.estimatedArrivalTime ?? "-"} / {plan.durationText ?? "-"}
          </p>
          <div className="mt-3 space-y-2">
            {plan.steps.slice(0, 4).map((step, index) => (
              <div
                key={`${step.instruction}-${index}`}
                className="rounded-2xl border border-stone-900/8 bg-white px-3 py-3"
              >
                <p className="text-sm font-medium text-stone-900">{step.instruction}</p>
                {step.lineName ? (
                  <p className="mt-1 text-xs text-stone-600">
                    {step.lineName}
                    {step.departureTime ? ` / ${step.departureTime}` : ""}
                    {step.arrivalTime ? ` -> ${step.arrivalTime}` : ""}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {status ? <p className="mt-4 text-sm leading-7 text-stone-600">{status}</p> : null}
    </section>
  );
}
