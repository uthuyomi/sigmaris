import { createAdminClient } from "@/lib/supabase/admin";
import { createClient } from "@/lib/supabase/server";

export type BillingPlan = "free" | "pro";

export type BillingStatus = {
  plan: BillingPlan;
  subscriptionStatus: string | null;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
};

const activeSubscriptionStatuses = new Set(["active", "trialing"]);

export const isProBillingStatus = (status: BillingStatus) => status.plan === "pro";

export const readBillingStatus = async (userId: string): Promise<BillingStatus> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("subscriptions")
    .select("status,current_period_end,cancel_at_period_end")
    .eq("user_id", userId)
    .in("status", [...activeSubscriptionStatuses])
    .order("current_period_end", { ascending: false, nullsFirst: false })
    .limit(1)
    .maybeSingle();

  if (error) {
    if (error.code === "42P01" || error.message.includes("subscriptions")) {
      return {
        plan: "free",
        subscriptionStatus: null,
        currentPeriodEnd: null,
        cancelAtPeriodEnd: false,
      };
    }
    throw new Error(error.message);
  }

  return {
    plan: data?.status && activeSubscriptionStatuses.has(data.status) ? "pro" : "free",
    subscriptionStatus: data?.status ?? null,
    currentPeriodEnd: data?.current_period_end ?? null,
    cancelAtPeriodEnd: Boolean(data?.cancel_at_period_end),
  };
};

export const readBillingStatusAdmin = async (userId: string): Promise<BillingStatus> => {
  const supabase = createAdminClient();
  const { data, error } = await supabase
    .from("subscriptions")
    .select("status,current_period_end,cancel_at_period_end")
    .eq("user_id", userId)
    .in("status", [...activeSubscriptionStatuses])
    .order("current_period_end", { ascending: false, nullsFirst: false })
    .limit(1)
    .maybeSingle();

  if (error) {
    throw new Error(error.message);
  }

  return {
    plan: data?.status && activeSubscriptionStatuses.has(data.status) ? "pro" : "free",
    subscriptionStatus: data?.status ?? null,
    currentPeriodEnd: data?.current_period_end ?? null,
    cancelAtPeriodEnd: Boolean(data?.cancel_at_period_end),
  };
};
