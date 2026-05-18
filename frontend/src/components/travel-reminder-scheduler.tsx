"use client";

import { BellRingIcon, NavigationIcon, RefreshCwIcon } from "lucide-react";
import { useEffect, useState } from "react";

type SubscriptionStatus = "idle" | "saving" | "saved" | "error";

const canUseNotifications = () =>
  typeof window !== "undefined" && "Notification" in window && "serviceWorker" in navigator;

const urlBase64ToUint8Array = (base64String: string) => {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = `${base64String}${padding}`.replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
};

const registerPushSubscription = async () => {
  const registration = await navigator.serviceWorker.ready;
  const keyResponse = await fetch("/api/push/public-key", { cache: "no-store" });
  const keyPayload = (await keyResponse.json()) as { publicKey?: string; error?: string };
  if (!keyResponse.ok || !keyPayload.publicKey) {
    throw new Error(keyPayload.error ?? "Web Push public key is unavailable.");
  }

  const existingSubscription = await registration.pushManager.getSubscription();
  const subscription =
    existingSubscription ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(keyPayload.publicKey),
    }));

  const response = await fetch("/api/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription.toJSON()),
  });
  const payload = (await response.json().catch(() => ({}))) as { error?: string };
  if (!response.ok) {
    throw new Error(payload.error ?? "Failed to save push subscription.");
  }
};

export function TravelReminderScheduler() {
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">(() =>
    canUseNotifications() ? Notification.permission : "unsupported",
  );
  const [subscriptionStatus, setSubscriptionStatus] = useState<SubscriptionStatus>("idle");
  const [enableError, setEnableError] = useState<string | null>(null);

  useEffect(() => {
    if (!canUseNotifications()) {
      return;
    }

    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    if (Notification.permission === "granted") {
      setSubscriptionStatus("saving");
      registerPushSubscription()
        .then(() => {
          setSubscriptionStatus("saved");
          setEnableError(null);
        })
        .catch((error) => {
          setSubscriptionStatus("error");
          setEnableError(error instanceof Error ? error.message : "Notification setup failed.");
        });
    }
  }, []);

  const enableNotifications = async () => {
    if (!canUseNotifications()) {
      setPermission("unsupported");
      return;
    }

    setEnableError(null);
    setSubscriptionStatus("saving");
    try {
      await navigator.serviceWorker.register("/sw.js");
      const nextPermission = await Notification.requestPermission();
      setPermission(nextPermission);
      if (nextPermission === "granted") {
        await registerPushSubscription();
        setSubscriptionStatus("saved");
      } else {
        setSubscriptionStatus("idle");
      }
    } catch (error) {
      setSubscriptionStatus("error");
      setEnableError(error instanceof Error ? error.message : "Notification setup failed.");
    }
  };

  if (
    permission === "unsupported" ||
    permission === "denied" ||
    (permission === "granted" && subscriptionStatus === "saved")
  ) {
    return null;
  }

  const needsRetry = permission === "granted" && subscriptionStatus === "error";
  const buttonLabel = needsRetry ? "Retry travel alerts" : "Enable travel alerts";

  return (
    <div className="fixed bottom-4 left-4 z-50 max-w-[calc(100vw-2rem)] rounded-2xl border border-stone-900/10 bg-white px-4 py-3 shadow-[0_18px_70px_-42px_rgba(28,25,23,0.8)] dark:border-white/10 dark:bg-[#2f2f2f]">
      <div className="flex items-center gap-3">
        <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-xl bg-stone-900 text-stone-50 dark:bg-white dark:text-stone-950">
          <BellRingIcon className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-stone-900 dark:text-stone-50">Travel alerts</p>
          <p className="text-xs text-stone-500 dark:text-stone-400">
            Save this phone for departure reminders.
          </p>
          {enableError ? <p className="mt-1 text-xs text-red-600">{enableError}</p> : null}
        </div>
        <button
          type="button"
          onClick={enableNotifications}
          disabled={subscriptionStatus === "saving"}
          className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-stone-900 text-stone-50 transition hover:bg-stone-700 dark:bg-white dark:text-stone-950 dark:hover:bg-stone-200"
          aria-label={buttonLabel}
        >
          {needsRetry ? <RefreshCwIcon className="size-4" /> : <NavigationIcon className="size-4" />}
        </button>
      </div>
    </div>
  );
}
