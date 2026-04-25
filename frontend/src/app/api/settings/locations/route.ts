// 役割: 保存済み地点の一覧取得と追加を行うNext.js API Route。

import { NextResponse } from "next/server";
import { z } from "zod";
import {
  createSavedLocationForUser,
  listSavedLocationsForUser,
  readHomeAddressForUser,
  updateHomeAddressForUser,
} from "@/lib/locations";
import { readPreferredTravelMode } from "@/lib/profile-settings";
import { createClient } from "@/lib/supabase/server";

const requestSchema = z.object({
  homeAddress: z.string().optional(),
  label: z.string().min(1).optional(),
  address: z.string().min(1).optional(),
  locationType: z.enum(["home", "work", "custom"]).optional(),
  isDefaultDeparture: z.boolean().optional(),
});

export async function GET() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const [homeAddress, locations, preferredTravelMode] = await Promise.all([
    readHomeAddressForUser(user.id),
    listSavedLocationsForUser(user.id),
    readPreferredTravelMode(user.id),
  ]);

  return NextResponse.json({ homeAddress, locations, preferredTravelMode });
}

export async function POST(request: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const input = requestSchema.parse(await request.json());

  if (typeof input.homeAddress === "string") {
    await updateHomeAddressForUser(user.id, input.homeAddress);
  }

  let createdLocation = null;
  if (input.label && input.address) {
    createdLocation = await createSavedLocationForUser({
      userId: user.id,
      label: input.label,
      address: input.address,
      locationType: input.locationType,
      isDefaultDeparture: input.isDefaultDeparture,
    });
  }

  const [homeAddress, locations, preferredTravelMode] = await Promise.all([
    readHomeAddressForUser(user.id),
    listSavedLocationsForUser(user.id),
    readPreferredTravelMode(user.id),
  ]);

  return NextResponse.json({
    ok: true,
    homeAddress,
    locations,
    preferredTravelMode,
    createdLocation,
  });
}
