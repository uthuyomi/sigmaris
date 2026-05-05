"use client";

import { useEffect, useState } from "react";

type IntegrationStatusPanelProps = {
  backendApiLabel: string;
  backendChatLabel: string;
  calendarReady: boolean;
  calendarLabel: string;
  integrationsLabel: string;
  loadingLabel: string;
  mapsLabel: string;
  mapsReady: boolean;
  missingLabel: string;
  readyLabel: string;
  sheetsLabel: string;
  sheetsReady: boolean;
  supabaseLabel: string;
  supabaseReady: boolean;
};

type BackendStatus = {
  health?: boolean;
  chat?: boolean;
};

export function IntegrationStatusPanel({
  backendApiLabel,
  backendChatLabel,
  calendarReady,
  calendarLabel,
  integrationsLabel,
  loadingLabel,
  mapsLabel,
  mapsReady,
  missingLabel,
  readyLabel,
  sheetsLabel,
  sheetsReady,
  supabaseLabel,
  supabaseReady,
}: IntegrationStatusPanelProps) {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>({});

  useEffect(() => {
    let ignore = false;

    const readStatus = async (path: string) => {
      try {
        const response = await fetch(path, { cache: "no-store" });
        return response.ok;
      } catch {
        return false;
      }
    };

    Promise.all([
      readStatus("/api/backend/health"),
      readStatus("/api/backend/chat-capabilities"),
    ]).then(([health, chat]) => {
      if (!ignore) {
        setBackendStatus({ health, chat });
      }
    });

    return () => {
      ignore = true;
    };
  }, []);

  const items = [
    { name: backendApiLabel, ready: backendStatus.health },
    { name: backendChatLabel, ready: backendStatus.chat },
    { name: supabaseLabel, ready: supabaseReady },
    { name: sheetsLabel, ready: sheetsReady },
    { name: calendarLabel, ready: calendarReady },
    { name: mapsLabel, ready: mapsReady },
  ];

  return (
    <section className="rounded-2xl border border-stone-900/10 bg-white p-5 shadow-sm dark:border-white/10 dark:bg-[#2f2f2f]">
      <p className="text-xs uppercase tracking-[0.3em] text-stone-500 dark:text-stone-400">
        {integrationsLabel}
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {items.map((item) => (
          <div
            key={item.name}
            className="rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-4 dark:border-white/10 dark:bg-white/6"
          >
            <p className="text-sm font-semibold text-stone-900 dark:text-stone-50">{item.name}</p>
            <p className="mt-2 text-sm text-stone-600 dark:text-stone-400">
              {item.ready === undefined ? loadingLabel : item.ready ? readyLabel : missingLabel}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
