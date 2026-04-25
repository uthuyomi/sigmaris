// 役割: 移動計画UIから呼び出すAPI通信処理をまとめる。

import type { PreferredTravelMode } from "@/lib/profile-settings";
import type { OriginType, ScheduleResponse, SavedLocation } from "@/components/mobility/types";

export const travelModeLabels: Record<PreferredTravelMode, string> = {
  car: "Car",
  bicycle: "Bicycle",
  walk: "Walk",
};

export const normalizeTravelMode = (value: unknown): PreferredTravelMode => {
  if (value === "bicycle" || value === "car" || value === "walk") {
    return value;
  }
  return "car";
};

export const readJsonSafely = async (response: Response) => {
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

export const loadLocationSettings = async () => {
  const response = await fetch("/api/settings/locations", { cache: "no-store" });
  if (!response.ok) return null;
  const data = await response.json();
  const locations = (data.locations ?? []) as SavedLocation[];

  return {
    homeAddress: data.homeAddress ?? "",
    locations,
    preferredTravelMode: normalizeTravelMode(data.preferredTravelMode),
  };
};

export const resolveCurrentLocation = () =>
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

export const requestSchedulePreview = async (input: {
  confirm: boolean;
  eventId: string;
  force: boolean;
  origin: string;
  originLabel: string;
  originType: OriginType;
  travelMode: PreferredTravelMode;
}) => {
  const response = await fetch("/api/mobility/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const data = (await readJsonSafely(response)) as Partial<ScheduleResponse> & {
    error?: string;
  };

  return { data, response };
};
