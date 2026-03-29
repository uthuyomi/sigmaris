import { NextResponse } from "next/server";
import { z } from "zod";
import {
  getSimpleRoutePlan,
  getTransitRoutePlan,
  hasGoogleMapsConfig,
} from "@/lib/google/maps";

const requestSchema = z.object({
  originType: z.enum(["home", "current", "custom"]),
  origin: z.string().min(1),
  destination: z.string().min(1),
  arrivalTimeIso: z.string(),
  departureTimeIso: z.string(),
  travelMode: z.enum(["transit", "driving", "walking"]),
});

export async function POST(req: Request) {
  if (!hasGoogleMapsConfig()) {
    return NextResponse.json(
      { error: "GOOGLE_MAPS_API_KEY is not set." },
      { status: 500 },
    );
  }

  const input = requestSchema.parse(await req.json());

  const plan =
    input.travelMode === "transit"
      ? await getTransitRoutePlan({
          origin: input.origin,
          destination: input.destination,
          arrivalTimeIso: input.arrivalTimeIso,
        })
      : await getSimpleRoutePlan({
          origin: input.origin,
          destination: input.destination,
          departureTimeIso: input.departureTimeIso,
          mode: input.travelMode,
        });

  return NextResponse.json({ ok: true, plan });
}
