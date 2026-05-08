type TravelMode = "bicycle" | "car" | "walk";

const googleMapsTravelMode: Record<TravelMode, string> = {
  bicycle: "bicycling",
  car: "driving",
  walk: "walking",
};

export const buildGoogleMapsDirectionsUrl = (input: {
  origin?: string | null;
  destination?: string | null;
  travelMode?: TravelMode | null;
}) => {
  const url = new URL("https://www.google.com/maps/dir/");
  url.searchParams.set("api", "1");

  if (input.origin) {
    url.searchParams.set("origin", input.origin);
  }

  if (input.destination) {
    url.searchParams.set("destination", input.destination);
  }

  if (input.travelMode) {
    url.searchParams.set("travelmode", googleMapsTravelMode[input.travelMode]);
  }

  return url.toString();
};
