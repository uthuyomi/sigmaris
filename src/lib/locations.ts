import { createClient } from "@/lib/supabase/server";

export type SavedLocation = {
  id: string;
  label: string;
  address: string;
  locationType: "home" | "work" | "custom";
  isDefaultDeparture: boolean;
};

export const listSavedLocationsForUser = async (userId: string) => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("saved_locations")
    .select("id,label,address,location_type,is_default_departure")
    .eq("user_id", userId)
    .order("is_default_departure", { ascending: false })
    .order("created_at", { ascending: true });

  if (error) {
    throw new Error(error.message);
  }

  return (data ?? []).map<SavedLocation>((item) => ({
    id: item.id,
    label: item.label,
    address: item.address,
    locationType: item.location_type,
    isDefaultDeparture: item.is_default_departure,
  }));
};

export const readHomeAddressForUser = async (userId: string) => {
  const supabase = await createClient();
  const { data, error } = await supabase.from("profiles").select("home_address").eq("id", userId).single();

  if (error) {
    throw new Error(error.message);
  }

  return data?.home_address ?? "";
};

export const updateHomeAddressForUser = async (userId: string, homeAddress: string) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("profiles")
    .update({ home_address: homeAddress.trim() || null })
    .eq("id", userId);

  if (error) {
    throw new Error(error.message);
  }
};

export const createSavedLocationForUser = async (input: {
  userId: string;
  label: string;
  address: string;
  locationType?: "home" | "work" | "custom";
  isDefaultDeparture?: boolean;
}) => {
  const supabase = await createClient();

  if (input.isDefaultDeparture) {
    const { error: resetError } = await supabase
      .from("saved_locations")
      .update({ is_default_departure: false })
      .eq("user_id", input.userId)
      .eq("is_default_departure", true);

    if (resetError) {
      throw new Error(resetError.message);
    }
  }

  const { data, error } = await supabase
    .from("saved_locations")
    .insert({
      user_id: input.userId,
      label: input.label.trim(),
      address: input.address.trim(),
      location_type: input.locationType ?? "custom",
      is_default_departure: Boolean(input.isDefaultDeparture),
    })
    .select("id,label,address,location_type,is_default_departure")
    .single();

  if (error) {
    throw new Error(error.message);
  }

  return {
    id: data.id,
    label: data.label,
    address: data.address,
    locationType: data.location_type,
    isDefaultDeparture: data.is_default_departure,
  } satisfies SavedLocation;
};

export const deleteSavedLocationForUser = async (userId: string, locationId: string) => {
  const supabase = await createClient();
  const { error } = await supabase
    .from("saved_locations")
    .delete()
    .eq("user_id", userId)
    .eq("id", locationId);

  if (error) {
    throw new Error(error.message);
  }
};
