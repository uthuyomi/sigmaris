"use client";
// 役割: 移動計画の入力・結果表示をまとめるReactクライアントコンポーネント。


import { getDictionary, type AppLocale } from "@/lib/i18n";
import {
  loadLocationSettings,
  type OriginType,
  OriginControls,
  requestSchedulePreview,
  ResolutionHintCard,
  resolveCurrentLocation,
  type RouteLookupResolution,
  type SavedLocation,
  SchedulePreviewCard,
  type ScheduleResponse,
  TravelModeControls,
} from "@/components/mobility";
import type { EventItem } from "@/lib/mock-schedule";
import type { PreferredTravelMode } from "@/lib/profile-settings";
import { MapPinnedIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

type MobilityPanelProps = {
  locale: AppLocale;
  selectedEvent?: EventItem;
};

export function MobilityPanel({ locale, selectedEvent }: MobilityPanelProps) {
  const dict = getDictionary(locale);
  const [travelMode, setTravelMode] = useState<PreferredTravelMode>("car");
  const [originType, setOriginType] = useState<OriginType>("home");
  const [origin, setOrigin] = useState("");
  const [savedLocations, setSavedLocations] = useState<SavedLocation[]>([]);
  const [homeAddress, setHomeAddress] = useState("");
  const [selectedSavedId, setSelectedSavedId] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [preview, setPreview] = useState<ScheduleResponse | null>(null);
  const [resolutionHint, setResolutionHint] = useState<RouteLookupResolution | null>(null);
  const [loading, setLoading] = useState(false);

  const selectedSaved = useMemo(
    () => savedLocations.find((location) => location.id === selectedSavedId),
    [savedLocations, selectedSavedId],
  );

  useEffect(() => {
    const load = async () => {
      const data = await loadLocationSettings();
      if (!data) return;
      const locations = data.locations;
      setSavedLocations(locations);
      setHomeAddress(data.homeAddress);
      setTravelMode(data.preferredTravelMode);
      const defaultLocation = locations.find((location) => location.isDefaultDeparture) ?? locations[0];
      if (defaultLocation) {
        setSelectedSavedId(defaultLocation.id);
      }
    };

    void load();
  }, []);

  useEffect(() => {
    if (originType === "home") {
      setOrigin(homeAddress);
    } else if (originType === "saved" && selectedSaved) {
      setOrigin(selectedSaved.address);
    }
  }, [originType, homeAddress, selectedSaved]);

  const buildOriginInput = async () => {
    if (originType === "current") {
      return resolveCurrentLocation();
    }

    if (originType === "saved" && selectedSaved) {
      return { origin: selectedSaved.address, label: selectedSaved.label };
    }

    return {
      origin,
      label: originType === "home" ? "Home" : "Custom",
    };
  };

  const runSchedule = async (confirm = false, force = false) => {
    if (!selectedEvent?.location) {
      setStatus("目的地なし");
      return;
    }

    setLoading(true);
    setStatus(null);
    setResolutionHint(null);

    try {
      const originInput = await buildOriginInput();
      const { data, response } = await requestSchedulePreview({
        eventId: selectedEvent.id,
        originType,
        origin: originInput.origin,
        originLabel: originInput.label,
        travelMode,
        confirm,
        force,
      });
      if (response.status === 409) {
        setPreview(data as ScheduleResponse);
        setStatus("重複あり");
        return;
      }
      if (!response.ok) {
        if ("routeLookup" in data && data.routeLookup && typeof data.routeLookup === "object") {
          const routeLookup = data.routeLookup as {
            resolution?: RouteLookupResolution;
          };
          if (routeLookup.resolution) {
            setResolutionHint(routeLookup.resolution);
          }
        }
        throw new Error(data.error ?? "移動調節に失敗");
      }

      setPreview(data as ScheduleResponse);
      setStatus(confirm ? "保存済み" : null);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "移動調節に失敗");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="rounded-[28px] border border-stone-900/10 bg-white p-4">
      <div className="flex items-start gap-3">
        <div className="inline-flex size-11 items-center justify-center rounded-2xl bg-stone-900 text-stone-50">
          <MapPinnedIcon className="size-5" />
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-stone-500">Mobility</p>
          <h3 className="mt-2 text-base font-semibold text-stone-900">
            {selectedEvent?.location ?? dict.common.unavailable}
          </h3>
          <p className="mt-2 text-sm leading-7 text-stone-600">
            出発地と移動手段から、到着に間に合う移動予定を作る。
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <OriginControls
          originType={originType}
          origin={origin}
          savedLocations={savedLocations}
          selectedSavedId={selectedSavedId}
          onOriginTypeChange={setOriginType}
          onOriginChange={setOrigin}
          onSavedLocationChange={setSelectedSavedId}
        />

        <TravelModeControls travelMode={travelMode} onTravelModeChange={setTravelMode} />

        <button
          type="button"
          disabled={loading || !selectedEvent?.location}
          onClick={() => runSchedule(false)}
          className="w-full rounded-full bg-stone-900 px-4 py-3 text-sm font-semibold text-stone-50 transition hover:bg-stone-800 disabled:opacity-50"
        >
          {loading ? dict.common.loading : "ルート確認"}
        </button>

        <p className="text-xs leading-6 text-stone-500">
          現在は車・自転車・徒歩で検索する。公共交通の自動検索は未対応。
        </p>
      </div>

      {resolutionHint ? (
        <ResolutionHintCard
          hint={resolutionHint}
          originType={originType}
          onOriginTypeChange={setOriginType}
          onOriginChange={setOrigin}
        />
      ) : null}

      {preview ? (
        <SchedulePreviewCard
          preview={preview}
          loading={loading}
          onConfirm={() => runSchedule(true, false)}
          onForceSave={() => runSchedule(true, true)}
        />
      ) : null}

      {status ? <p className="mt-4 text-sm leading-7 text-stone-600">{status}</p> : null}
    </section>
  );
}
