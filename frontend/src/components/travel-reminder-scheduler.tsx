"use client";

import { BellRingIcon, NavigationIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const POLL_INTERVAL_MS = 60_000;
const LOOKAHEAD_HOURS = 24;
const REMINDER_LEAD_MS = 5 * 60_000;
const FIRED_STORAGE_KEY = "shiftpilotai-fired-travel-reminders";

type TravelReminder = {
  id: string;
  title: string;
  description?: string | null;
  startsAt: string;
  endsAt: string;
  originLabel: string;
  destinationLabel: string;
  navigationUrl: string;
};

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

const readFiredReminderKeys = () => {
  try {
    const raw = window.localStorage.getItem(FIRED_STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
};

const rememberFiredReminder = (key: string) => {
  const next = [key, ...readFiredReminderKeys().filter((item) => item !== key)].slice(0, 200);
  window.localStorage.setItem(FIRED_STORAGE_KEY, JSON.stringify(next));
};

const reminderKey = (reminder: TravelReminder) => `${reminder.id}:${reminder.startsAt}`;

const formatStartTime = (value: string) =>
  new Intl.DateTimeFormat("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Tokyo",
  }).format(new Date(value));

async function showTravelNotification(reminder: TravelReminder) {
  const registration = await navigator.serviceWorker.ready;
  const startTime = formatStartTime(reminder.startsAt);
  const options = {
    body: `${startTime} departure. Tap to open Google Maps navigation.`,
    tag: reminderKey(reminder),
    icon: "/images/icon/icon.png",
    badge: "/images/icon/icon.png",
    data: {
      navigationUrl: reminder.navigationUrl,
      reminderId: reminder.id,
    },
    actions: [
      {
        action: "navigate",
        title: "Start navigation",
      },
    ],
  } as NotificationOptions;

  await registration.showNotification(`Travel time: ${reminder.destinationLabel}`, options);
}

export function TravelReminderScheduler() {
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">(() =>
    canUseNotifications() ? Notification.permission : "unsupported",
  );
  const [enableError, setEnableError] = useState<string | null>(null);
  const timersRef = useRef<number[]>([]);

  useEffect(() => {
    if (!canUseNotifications()) {
      return;
    }

    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    if (Notification.permission === "granted") {
      registerPushSubscription().catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    if (permission !== "granted") return;

    let active = true;

    const clearTimers = () => {
      for (const timer of timersRef.current) {
        window.clearTimeout(timer);
      }
      timersRef.current = [];
    };

    const loadAndSchedule = async () => {
      const response = await fetch(`/api/travel-reminders?lookaheadHours=${LOOKAHEAD_HOURS}`, {
        cache: "no-store",
      });
      if (!response.ok) return;

      const payload = (await response.json()) as { reminders?: TravelReminder[] };
      if (!active) return;

      clearTimers();
      const firedKeys = new Set(readFiredReminderKeys());
      const now = Date.now();

      for (const reminder of payload.reminders ?? []) {
        if (!reminder.navigationUrl) continue;
        const key = reminderKey(reminder);
        if (firedKeys.has(key)) continue;

        const delay = new Date(reminder.startsAt).getTime() - REMINDER_LEAD_MS - now;
        if (delay < 0) continue;

        const timer = window.setTimeout(() => {
          void showTravelNotification(reminder).then(() => rememberFiredReminder(key));
        }, delay);
        timersRef.current.push(timer);
      }
    };

    void loadAndSchedule();
    const interval = window.setInterval(loadAndSchedule, POLL_INTERVAL_MS);

    return () => {
      active = false;
      window.clearInterval(interval);
      clearTimers();
    };
  }, [permission]);

  const enableNotifications = async () => {
    if (!canUseNotifications()) {
      setPermission("unsupported");
      return;
    }

    setEnableError(null);
    try {
      await navigator.serviceWorker.register("/sw.js");
      const nextPermission = await Notification.requestPermission();
      setPermission(nextPermission);
      if (nextPermission === "granted") {
        await registerPushSubscription();
      }
    } catch (error) {
      setEnableError(error instanceof Error ? error.message : "Notification setup failed.");
    }
  };

  if (permission === "granted" || permission === "denied" || permission === "unsupported") {
    return null;
  }

  return (
    <div className="fixed bottom-4 left-4 z-50 max-w-[calc(100vw-2rem)] rounded-2xl border border-stone-900/10 bg-white px-4 py-3 shadow-[0_18px_70px_-42px_rgba(28,25,23,0.8)] dark:border-white/10 dark:bg-[#2f2f2f]">
      <div className="flex items-center gap-3">
        <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-xl bg-stone-900 text-stone-50 dark:bg-white dark:text-stone-950">
          <BellRingIcon className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-stone-900 dark:text-stone-50">Travel alerts</p>
          <p className="text-xs text-stone-500 dark:text-stone-400">
            Notify at departure time with a Google Maps button.
          </p>
          {enableError ? <p className="mt-1 text-xs text-red-600">{enableError}</p> : null}
        </div>
        <button
          type="button"
          onClick={enableNotifications}
          className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-stone-900 text-stone-50 transition hover:bg-stone-700 dark:bg-white dark:text-stone-950 dark:hover:bg-stone-200"
          aria-label="Enable travel alerts"
        >
          <NavigationIcon className="size-4" />
        </button>
      </div>
    </div>
  );
}
