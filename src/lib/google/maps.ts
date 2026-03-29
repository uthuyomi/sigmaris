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
  recommendedDepartureIso?: string;
  estimatedArrivalTime?: string;
  estimatedArrivalIso?: string;
  durationText?: string;
  durationSeconds?: number;
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
  departure_time?: { text?: string; value?: number };
  arrival_time?: { text?: string; value?: number };
  duration?: { text?: string; value?: number };
  duration_in_traffic?: { text?: string; value?: number };
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

const toIsoFromEpochSeconds = (epochSeconds?: number) =>
  epochSeconds ? new Date(epochSeconds * 1000).toISOString() : undefined;

const buildRouteLookupError = (input: {
  mode: TravelMode;
  status?: string;
  errorMessage?: string;
}) => {
  if (input.errorMessage) {
    return `${input.errorMessage} (Google Maps status: ${input.status ?? "UNKNOWN"})`;
  }

  if (input.status === "ZERO_RESULTS") {
    return input.mode === "transit"
      ? "No public transit route was found for this origin, destination, or arrival time."
      : "No route was found for this origin and destination.";
  }

  if (input.status === "REQUEST_DENIED") {
    return "Google Maps request was denied. Check the API key and enabled APIs.";
  }

  if (input.status === "OVER_QUERY_LIMIT") {
    return "Google Maps query limit was reached.";
  }

  if (input.status === "INVALID_REQUEST") {
    return "Google Maps request was invalid. Check the origin, destination, and arrival time.";
  }

  return `Google Maps route lookup failed. (status: ${input.status ?? "UNKNOWN"})`;
};

const parseDirectionsResponse = async (url: URL, mode: TravelMode) => {
  const response = await fetch(url.toString(), { cache: "no-store" });
  const data = (await response.json()) as DirectionsApiResponse;

  if (!response.ok || data.status !== "OK" || !data.routes?.length) {
    throw new Error(
      buildRouteLookupError({
        mode,
        status: data.status,
        errorMessage: data.error_message,
      }),
    );
  }

  const route = data.routes[0];
  const leg = route.legs?.[0];

  if (!leg) {
    throw new Error("No route leg returned from Google Maps.");
  }

  return leg;
};

const buildCommonSteps = (leg: DirectionsApiLeg) =>
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
  })) ?? [];

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

  const leg = await parseDirectionsResponse(url, "transit");

  return {
    mode: "transit" as const,
    originLabel: leg.start_address ?? input.origin,
    destinationLabel: leg.end_address ?? input.destination,
    recommendedDepartureTime:
      leg.departure_time?.text ?? formatEpochSeconds(leg.departure_time?.value),
    recommendedDepartureIso: toIsoFromEpochSeconds(leg.departure_time?.value),
    estimatedArrivalTime: leg.arrival_time?.text ?? formatEpochSeconds(leg.arrival_time?.value),
    estimatedArrivalIso: toIsoFromEpochSeconds(leg.arrival_time?.value),
    durationText: leg.duration?.text,
    durationSeconds: leg.duration?.value,
    steps: buildCommonSteps(leg),
  } satisfies RoutePlan;
};

export const getSimpleRoutePlan = async (input: {
  origin: string;
  destination: string;
  arrivalTimeIso: string;
  mode: Exclude<TravelMode, "transit">;
}) => {
  if (!process.env.GOOGLE_MAPS_API_KEY) {
    throw new Error("GOOGLE_MAPS_API_KEY is not set.");
  }

  const targetArrival = new Date(input.arrivalTimeIso);
  const url = new URL("https://maps.googleapis.com/maps/api/directions/json");
  url.searchParams.set("origin", input.origin);
  url.searchParams.set("destination", input.destination);
  url.searchParams.set("mode", input.mode);
  url.searchParams.set(
    "departure_time",
    `${Math.floor(targetArrival.getTime() / 1000)}`,
  );
  url.searchParams.set("language", "ja");
  url.searchParams.set("region", "jp");
  url.searchParams.set("key", process.env.GOOGLE_MAPS_API_KEY);

  const leg = await parseDirectionsResponse(url, input.mode);
  const durationSeconds = leg.duration_in_traffic?.value ?? leg.duration?.value ?? 0;
  const recommendedDeparture = new Date(targetArrival.getTime() - durationSeconds * 1000);

  return {
    mode: input.mode,
    originLabel: leg.start_address ?? input.origin,
    destinationLabel: leg.end_address ?? input.destination,
    recommendedDepartureTime: new Intl.DateTimeFormat("ja-JP", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "Asia/Tokyo",
    }).format(recommendedDeparture),
    recommendedDepartureIso: recommendedDeparture.toISOString(),
    estimatedArrivalTime: new Intl.DateTimeFormat("ja-JP", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "Asia/Tokyo",
    }).format(targetArrival),
    estimatedArrivalIso: targetArrival.toISOString(),
    durationText: leg.duration_in_traffic?.text ?? leg.duration?.text,
    durationSeconds,
    steps: buildCommonSteps(leg),
  } satisfies RoutePlan;
};
