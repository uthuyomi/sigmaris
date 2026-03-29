export type TravelMode = "transit" | "driving" | "walking";

export type RoutePlanStep = {
  instruction: string;
  travelMode: string;
  lineName?: string;
  departureStop?: string;
  arrivalStop?: string;
  departureTime?: string;
  arrivalTime?: string;
};

export type RoutePlan = {
  mode: TravelMode;
  originLabel: string;
  destinationLabel: string;
  recommendedDepartureTime?: string;
  estimatedArrivalTime?: string;
  durationText?: string;
  steps: RoutePlanStep[];
};

type DirectionsApiTransitDetails = {
  departure_stop?: { name?: string };
  arrival_stop?: { name?: string };
  departure_time?: { text?: string; value?: number };
  arrival_time?: { text?: string; value?: number };
  line?: { short_name?: string; name?: string };
};

type DirectionsApiStep = {
  html_instructions?: string;
  travel_mode?: string;
  transit_details?: DirectionsApiTransitDetails;
};

type DirectionsApiLeg = {
  start_address?: string;
  end_address?: string;
  departure_time?: { text?: string };
  arrival_time?: { text?: string };
  duration?: { text?: string };
  duration_in_traffic?: { text?: string };
  steps?: DirectionsApiStep[];
};

type DirectionsApiRoute = {
  legs?: DirectionsApiLeg[];
};

type DirectionsApiResponse = {
  status?: string;
  error_message?: string;
  routes?: DirectionsApiRoute[];
};

export const hasGoogleMapsConfig = () => Boolean(process.env.GOOGLE_MAPS_API_KEY);

const stripHtml = (value: string | undefined) =>
  (value ?? "").replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();

const formatEpochSeconds = (epochSeconds?: number) => {
  if (!epochSeconds) return undefined;

  return new Intl.DateTimeFormat("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Tokyo",
  }).format(new Date(epochSeconds * 1000));
};

const parseDirectionsResponse = async (url: URL) => {
  const response = await fetch(url.toString(), { cache: "no-store" });
  const data = (await response.json()) as DirectionsApiResponse;

  if (!response.ok || data.status !== "OK" || !data.routes?.length) {
    throw new Error(data.error_message ?? "Google Maps から経路を取得できませんでした。");
  }

  const route = data.routes[0];
  const leg = route.legs?.[0];

  if (!leg) {
    throw new Error("経路データに移動区間が含まれていません。");
  }

  return leg;
};

export const getTransitRoutePlan = async (input: {
  origin: string;
  destination: string;
  arrivalTimeIso: string;
}) => {
  if (!process.env.GOOGLE_MAPS_API_KEY) {
    throw new Error("GOOGLE_MAPS_API_KEY is not set.");
  }

  const url = new URL("https://maps.googleapis.com/maps/api/directions/json");
  url.searchParams.set("origin", input.origin);
  url.searchParams.set("destination", input.destination);
  url.searchParams.set("mode", "transit");
  url.searchParams.set(
    "arrival_time",
    `${Math.floor(new Date(input.arrivalTimeIso).getTime() / 1000)}`,
  );
  url.searchParams.set("transit_mode", "rail|bus");
  url.searchParams.set("language", "ja");
  url.searchParams.set("region", "jp");
  url.searchParams.set("key", process.env.GOOGLE_MAPS_API_KEY);

  const leg = await parseDirectionsResponse(url);

  return {
    mode: "transit" as const,
    originLabel: leg.start_address ?? input.origin,
    destinationLabel: leg.end_address ?? input.destination,
    recommendedDepartureTime: leg.departure_time?.text,
    estimatedArrivalTime: leg.arrival_time?.text,
    durationText: leg.duration?.text,
    steps:
      leg.steps?.map((step) => ({
        instruction: stripHtml(step.html_instructions),
        travelMode: step.travel_mode ?? "UNKNOWN",
        lineName: step.transit_details?.line?.short_name ?? step.transit_details?.line?.name,
        departureStop: step.transit_details?.departure_stop?.name,
        arrivalStop: step.transit_details?.arrival_stop?.name,
        departureTime:
          step.transit_details?.departure_time?.text ??
          formatEpochSeconds(step.transit_details?.departure_time?.value),
        arrivalTime:
          step.transit_details?.arrival_time?.text ??
          formatEpochSeconds(step.transit_details?.arrival_time?.value),
      })) ?? [],
  };
};

export const getSimpleRoutePlan = async (input: {
  origin: string;
  destination: string;
  departureTimeIso: string;
  mode: Exclude<TravelMode, "transit">;
}) => {
  if (!process.env.GOOGLE_MAPS_API_KEY) {
    throw new Error("GOOGLE_MAPS_API_KEY is not set.");
  }

  const url = new URL("https://maps.googleapis.com/maps/api/directions/json");
  url.searchParams.set("origin", input.origin);
  url.searchParams.set("destination", input.destination);
  url.searchParams.set("mode", input.mode);
  url.searchParams.set(
    "departure_time",
    `${Math.floor(new Date(input.departureTimeIso).getTime() / 1000)}`,
  );
  url.searchParams.set("language", "ja");
  url.searchParams.set("region", "jp");
  url.searchParams.set("key", process.env.GOOGLE_MAPS_API_KEY);

  const leg = await parseDirectionsResponse(url);

  return {
    mode: input.mode,
    originLabel: leg.start_address ?? input.origin,
    destinationLabel: leg.end_address ?? input.destination,
    durationText: leg.duration_in_traffic?.text ?? leg.duration?.text,
    steps:
      leg.steps?.map((step) => ({
        instruction: stripHtml(step.html_instructions),
        travelMode: step.travel_mode ?? "UNKNOWN",
      })) ?? [],
  };
};
