"use client";

import { CreditCardIcon, ExternalLinkIcon, SparklesIcon } from "lucide-react";
import { useState, useTransition } from "react";
import type { BillingStatus } from "@/lib/billing";
import { PRO_MONTHLY_PRICE_JPY } from "@/lib/stripe";

type BillingPanelProps = {
  initialBilling: BillingStatus;
};

const openBillingUrl = async (endpoint: string) => {
  const response = await fetch(endpoint, { method: "POST" });
  const payload = (await response.json()) as { url?: string; error?: string };
  if (!response.ok || !payload.url) {
    throw new Error(payload.error ?? "Billing request failed.");
  }

  window.location.assign(payload.url);
};

export function BillingPanel({ initialBilling }: BillingPanelProps) {
  const [billing] = useState(initialBilling);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const isPro = billing.plan === "pro";

  const runBillingAction = (endpoint: string) => {
    setError(null);
    startTransition(async () => {
      try {
        await openBillingUrl(endpoint);
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : "Billing request failed.");
      }
    });
  };

  return (
    <section className="rounded-2xl border border-stone-900/10 bg-stone-50 p-4 dark:border-white/10 dark:bg-white/6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="settings-item-icon inline-flex size-11 items-center justify-center rounded-xl">
            {isPro ? <SparklesIcon className="size-5" /> : <CreditCardIcon className="size-5" />}
          </div>
          <h2 className="mt-4 text-lg font-semibold text-stone-900 dark:text-stone-50">
            ShiftPilotAI Pro
          </h2>
          <p className="mt-2 max-w-md text-sm leading-7 text-stone-600 dark:text-stone-400">
            Google Calendar sync, schedule imports, travel planning, and departure notifications.
          </p>
        </div>

        <div className="rounded-full bg-stone-900 px-3 py-1.5 text-xs font-semibold text-stone-50 dark:bg-white dark:text-stone-950">
          {isPro ? "Pro" : "Free"}
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-stone-900/10 bg-white px-4 py-3 dark:border-white/10 dark:bg-white/6">
        <p className="text-sm font-semibold text-stone-900 dark:text-stone-50">
          {isPro ? "Active subscription" : `¥${PRO_MONTHLY_PRICE_JPY.toLocaleString("ja-JP")} / month`}
        </p>
        <p className="mt-1 text-xs leading-6 text-stone-500 dark:text-stone-400">
          {isPro
            ? billing.cancelAtPeriodEnd
              ? "Your plan stays active until the current period ends."
              : "Your Pro features are enabled."
            : "Upgrade when you want the connected calendar and mobility automation features."}
        </p>
      </div>

      <button
        type="button"
        disabled={isPending}
        onClick={() => runBillingAction(isPro ? "/api/billing/portal" : "/api/billing/checkout")}
        className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-full bg-stone-900 px-4 text-sm font-semibold text-stone-50 transition hover:bg-stone-800 disabled:opacity-60 dark:bg-white dark:text-stone-950 dark:hover:bg-stone-200"
      >
        <ExternalLinkIcon className="size-4" />
        {isPending ? "Opening..." : isPro ? "Manage billing" : "Upgrade to Pro"}
      </button>

      {error ? <p className="mt-3 text-sm leading-6 text-red-600">{error}</p> : null}
    </section>
  );
}
