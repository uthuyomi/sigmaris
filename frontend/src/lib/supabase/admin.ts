import { createClient } from "@supabase/supabase-js";

export const hasSupabaseAdminConfig = () =>
  Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.SUPABASE_SERVICE_ROLE_KEY);

export const createAdminClient = () => {
  if (!hasSupabaseAdminConfig()) {
    throw new Error("Supabase admin environment variables are not configured.");
  }

  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    {
      auth: {
        persistSession: false,
        autoRefreshToken: false,
      },
    },
  );
};
