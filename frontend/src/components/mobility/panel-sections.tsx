"use client";
// 役割: 移動計画パネル内の各表示セクションをまとめるReactコンポーネント群。


import { travelModeLabels } from "@/components/mobility/api";
import type {
  OriginType,
  RouteLookupResolution,
  SavedLocation,
  ScheduleResponse,
} from "@/components/mobility/types";
import type { PreferredTravelMode } from "@/lib/profile-settings";
import { AlertTriangleIcon, CheckIcon, NavigationIcon, PlusCircleIcon } from "lucide-react";

type OriginControlsProps = {
  originType: OriginType;
  origin: string;
  savedLocations: SavedLocation[];
  selectedSavedId: string;
  onOriginTypeChange: (value: OriginType) => void;
  onOriginChange: (value: string) => void;
  onSavedLocationChange: (value: string) => void;
};

export function OriginControls({
  originType,
  origin,
  savedLocations,
  selectedSavedId,
  onOriginTypeChange,
  onOriginChange,
  onSavedLocationChange,
}: OriginControlsProps) {
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {(["home", "current", "saved", "custom"] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => onOriginTypeChange(value)}
            className={`rounded-full px-3 py-2 text-xs font-medium ${
              originType === value ? "bg-stone-900 text-stone-50" : "bg-stone-100 text-stone-700"
            }`}
          >
            {value === "home"
              ? "Home"
              : value === "current"
                ? "GPS"
                : value === "saved"
                  ? "Saved"
                  : "Custom"}
          </button>
        ))}
      </div>

      {originType === "saved" ? (
        <select
          value={selectedSavedId}
          onChange={(event) => onSavedLocationChange(event.target.value)}
          className="w-full rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-3 text-sm outline-none"
        >
          <option value="">保存地点</option>
          {savedLocations.map((location) => (
            <option key={location.id} value={location.id}>
              {location.label}
            </option>
          ))}
        </select>
      ) : originType !== "current" ? (
        <input
          value={origin}
          onChange={(event) => onOriginChange(event.target.value)}
          placeholder={originType === "home" ? "自宅住所" : "出発地"}
          className="w-full rounded-2xl border border-stone-900/10 bg-stone-50 px-4 py-3 text-sm outline-none"
        />
      ) : null}
    </>
  );
}

type TravelModeControlsProps = {
  travelMode: PreferredTravelMode;
  onTravelModeChange: (value: PreferredTravelMode) => void;
};

export function TravelModeControls({ travelMode, onTravelModeChange }: TravelModeControlsProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {(["car", "bicycle", "walk"] as const).map((value) => (
        <button
          key={value}
          type="button"
          onClick={() => onTravelModeChange(value)}
          className={`rounded-full px-3 py-2 text-xs font-medium ${
            travelMode === value ? "bg-[#e76f51] text-white" : "bg-stone-100 text-stone-700"
          }`}
        >
          {travelModeLabels[value]}
        </button>
      ))}
    </div>
  );
}

type ResolutionHintCardProps = {
  hint: RouteLookupResolution;
  originType: OriginType;
  onOriginTypeChange: (value: OriginType) => void;
  onOriginChange: (value: string) => void;
};

export function ResolutionHintCard({
  hint,
  originType,
  onOriginTypeChange,
  onOriginChange,
}: ResolutionHintCardProps) {
  return (
    <div className="mt-4 rounded-[24px] border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-950">
      <p className="font-semibold">
        {hint.target === "origin" ? "出発地を特定できません" : "目的地を特定できません"}
      </p>
      <p className="mt-2 text-xs leading-6 text-amber-900">入力: {hint.query}</p>
      {hint.candidates.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {hint.candidates.map((candidate) => (
            <button
              key={`${candidate.formattedAddress}-${candidate.placeId ?? "manual"}`}
              type="button"
              onClick={() => {
                if (hint.target === "origin") {
                  onOriginChange(candidate.formattedAddress);
                  if (originType === "saved") {
                    onOriginTypeChange("custom");
                  }
                }
              }}
              className="rounded-full border border-amber-300 bg-white px-3 py-2 text-left text-xs text-amber-950 transition hover:bg-amber-100"
            >
              {candidate.formattedAddress}
            </button>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-xs leading-6 text-amber-900">住所を詳しく入力。</p>
      )}
    </div>
  );
}

type SchedulePreviewCardProps = {
  preview: ScheduleResponse;
  loading: boolean;
  onConfirm: () => void;
  onForceSave: () => void;
};

export function SchedulePreviewCard({
  preview,
  loading,
  onConfirm,
  onForceSave,
}: SchedulePreviewCardProps) {
  return (
    <div className="mt-4 space-y-3 rounded-[24px] border border-stone-900/10 bg-stone-50 p-4">
      <div>
        <p className="text-sm font-semibold text-stone-900">
          {preview.routePlan.recommendedDepartureTime ?? "--:--"} -{" "}
          {preview.routePlan.estimatedArrivalTime ?? "--:--"}
        </p>
        <p className="mt-1 text-sm text-stone-600">{preview.routePlan.durationText ?? "-"}</p>
        <p className="mt-1 text-xs text-stone-500">
          {travelModeLabels[preview.routePlan.mode]} / 徒歩{" "}
          {preview.routePlan.walkingDistanceText ?? "-"}
        </p>
        {preview.arrivalLeadMinutes !== undefined ? (
          <p className="mt-1 text-xs text-stone-500">
            {preview.arrivalLeadMinutes}分前着。
          </p>
        ) : null}
      </div>

      <div className="rounded-2xl border border-stone-900/8 bg-white px-3 py-3">
        <p className="text-xs uppercase tracking-[0.18em] text-stone-500">移動</p>
        <p className="mt-2 text-sm font-semibold text-stone-900">{preview.travelEvent.title}</p>
        <p className="mt-1 text-xs text-stone-500">
          {preview.travelEvent.startsAt} - {preview.travelEvent.endsAt}
        </p>
      </div>

      {preview.warnings.length ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-3 text-amber-900">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <AlertTriangleIcon className="size-4" />
            重複あり
          </div>
          <div className="mt-2 space-y-2 text-xs leading-6">
            {preview.warnings.map((warning) => (
              <div key={warning.id}>
                {warning.title} / {warning.startsAt} - {warning.endsAt}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="space-y-2">
        {preview.routePlan.steps.slice(0, 4).map((step, index) => (
          <div
            key={`${step.instruction}-${index}`}
            className="rounded-2xl border border-stone-900/8 bg-white px-3 py-3"
          >
            <p className="text-sm font-medium text-stone-900">{step.instruction}</p>
            <p className="mt-1 text-xs text-stone-600">
              {step.departureTime ? `${step.departureTime}` : ""}
              {step.arrivalTime ? ` - ${step.arrivalTime}` : ""}
              {step.durationText ? ` / ${step.durationText}` : ""}
              {step.distanceText ? ` / ${step.distanceText}` : ""}
            </p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {preview.mapsNavigationUrl ? (
          <a
            href={preview.mapsNavigationUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-full border border-stone-900/15 bg-white px-4 py-2 text-sm font-semibold text-stone-900"
          >
            <NavigationIcon className="size-4" />
            Maps
          </a>
        ) : null}
        <button
          type="button"
          onClick={onConfirm}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-full bg-stone-900 px-4 py-2 text-sm font-semibold text-stone-50"
        >
          <CheckIcon className="size-4" />
          保存
        </button>
        {preview.warnings.length ? (
          <button
            type="button"
            onClick={onForceSave}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-full bg-amber-600 px-4 py-2 text-sm font-semibold text-white"
          >
            <PlusCircleIcon className="size-4" />
            強制保存
          </button>
        ) : null}
      </div>

      {preview.willSyncToGoogle ? (
        <p className="text-xs text-stone-500">Google同期あり。</p>
      ) : null}
      {preview.savedToGoogle ? (
        <p className="text-xs text-stone-500">Googleにも保存済み。</p>
      ) : null}
    </div>
  );
}
