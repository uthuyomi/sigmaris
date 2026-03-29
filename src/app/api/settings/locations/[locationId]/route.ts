import { NextResponse } from "next/server";
import { deleteSavedLocationForUser, listSavedLocationsForUser, readHomeAddressForUser } from "@/lib/locations";
import { createClient } from "@/lib/supabase/server";

type Params = {
  params: Promise<{
    locationId: string;
  }>;
};

export async function DELETE(_: Request, { params }: Params) {
  const resolved = await params;
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  await deleteSavedLocationForUser(user.id, resolved.locationId);
  const [homeAddress, locations] = await Promise.all([
    readHomeAddressForUser(user.id),
    listSavedLocationsForUser(user.id),
  ]);

  return NextResponse.json({ ok: true, homeAddress, locations });
}
