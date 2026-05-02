"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { createClient } from "@/lib/supabase/client";

const GOOGLE_SYNC_INTERVAL_MS = 20_000;

type CalendarLiveSyncProps = {
  userId: string;
  syncEnabled: boolean;
};

export function CalendarLiveSync({ userId, syncEnabled }: CalendarLiveSyncProps) {
  const router = useRouter();
  const syncInFlightRef = useRef(false);

  useEffect(() => {
    let active = true;
    const supabase = createClient();
    const channel = supabase
      .channel(`calendar-events-${userId}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "events",
          filter: `user_id=eq.${userId}`,
        },
        () => {
          if (active) {
            router.refresh();
          }
        },
      )
      .subscribe();

    return () => {
      active = false;
      supabase.removeChannel(channel);
    };
  }, [router, userId]);

  useEffect(() => {
    if (!syncEnabled) return;

    let active = true;

    const syncGoogleCalendar = async () => {
      if (syncInFlightRef.current) return;
      syncInFlightRef.current = true;

      try {
        const response = await fetch("/api/sync/google-calendar", {
          method: "POST",
        });
        if (active && response.ok) {
          router.refresh();
        }
      } finally {
        syncInFlightRef.current = false;
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void syncGoogleCalendar();
      }
    };

    void syncGoogleCalendar();
    const interval = window.setInterval(syncGoogleCalendar, GOOGLE_SYNC_INTERVAL_MS);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("focus", syncGoogleCalendar);

    return () => {
      active = false;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("focus", syncGoogleCalendar);
    };
  }, [router, syncEnabled]);

  return null;
}
