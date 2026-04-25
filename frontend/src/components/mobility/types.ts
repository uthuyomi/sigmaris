// 役割: 移動計画UIで使う型定義をまとめる。

import type { PreferredTravelMode } from "@/lib/profile-settings";

export type SavedLocation = {
  id: string;
  label: string;
  address: string;
  locationType: "home" | "work" | "custom";
  isDefaultDeparture: boolean;
};

export type ScheduleResponse = {
  routePlan: {
    mode: PreferredTravelMode;
    originLabel: string;
    destinationLabel: string;
    recommendedDepartureTime?: string;
    estimatedArrivalTime?: string;
    durationText?: string;
    walkingDurationText?: string;
    walkingDistanceText?: string;
    transferCount?: number;
    fareText?: string;
    routeSummary?: string;
    steps: Array<{
      instruction: string;
      lineName?: string;
      departureTime?: string;
      arrivalTime?: string;
      distanceText?: string;
      durationText?: string;
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
  arrivalLeadMinutes?: number;
  desiredArrivalIso?: string;
  willSyncToGoogle?: boolean;
  savedToGoogle?: boolean;
};

export type RouteLookupCandidate = {
  formattedAddress: string;
  latitude: number;
  longitude: number;
  placeId?: string;
};

export type RouteLookupResolution = {
  target: "origin" | "destination";
  query: string;
  candidates: RouteLookupCandidate[];
};

export type OriginType = "home" | "current" | "saved" | "custom";
