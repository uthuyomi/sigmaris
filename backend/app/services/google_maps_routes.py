from __future__ import annotations

# 役割: Google Directions の結果を RoutePlan に変換する。

from datetime import datetime, timedelta

from app.schemas.mobility import RouteLookupResolution, RoutePlan, RoutePlanStep, SurfaceTravelMode, TravelMode
from app.services.google_maps_core import (
    JST,
    UTC,
    RouteLookupError,
    ResolvedLocation,
    _build_route_lookup_error,
    _floor_to_minute,
    _format_epoch_seconds,
    _google_get,
    _strip_html,
    _sum_step_metric,
    _to_iso_from_epoch_seconds,
    logger,
)
from app.services.google_maps_locations import resolve_location


async def _parse_directions_response(
    params: dict[str, str],
    mode: TravelMode,
    destination_resolution: ResolvedLocation,
) -> tuple[dict, dict]:
    logger.info(
        "google maps directions lookup mode=%s origin=%s destination=%s departure_time=%s",
        mode,
        params.get("origin"),
        params.get("destination"),
        params.get("departure_time"),
    )
    data = await _google_get("https://maps.googleapis.com/maps/api/directions/json", params)
    if data.get("status") != "OK" or not data.get("routes"):
        raise RouteLookupError(
            _build_route_lookup_error(data.get("status"), data.get("error_message")),
            mode=mode,
            status=data.get("status"),
            resolution=RouteLookupResolution(
                target="destination",
                query=destination_resolution.formatted_address,
                candidates=destination_resolution.candidates,
            )
            if data.get("status") == "NOT_FOUND"
            else None,
        )
    route = data["routes"][0]
    leg = route.get("legs", [None])[0]
    if not leg:
        raise RouteLookupError("No route leg returned from Google Maps.", mode=mode, status=data.get("status"))
    return route, leg


def _build_steps(leg: dict) -> list[RoutePlanStep]:
    steps: list[RoutePlanStep] = []
    for step in leg.get("steps", []):
        steps.append(
            RoutePlanStep(
                instruction=_strip_html(step.get("html_instructions")),
                travelMode=step.get("travel_mode", "UNKNOWN"),
                distanceText=step.get("distance", {}).get("text"),
                durationText=step.get("duration", {}).get("text"),
            )
        )
    return steps


def _build_route_summary(steps: list[RoutePlanStep]) -> str | None:
    instructions = [step.instruction for step in steps if step.instruction]
    return " -> ".join(instructions[:2]) if instructions else None


def _build_route_plan(
    *,
    mode: TravelMode,
    leg: dict,
    fallback_origin: str,
    fallback_destination: str,
) -> RoutePlan:
    raw_steps = leg.get("steps", [])
    steps = _build_steps(leg)
    walking_duration_seconds = _sum_step_metric(raw_steps, field="duration", travel_mode="WALKING")
    walking_distance_meters = _sum_step_metric(raw_steps, field="distance", travel_mode="WALKING")

    return RoutePlan(
        mode=mode,
        originLabel=leg.get("start_address") or fallback_origin,
        destinationLabel=leg.get("end_address") or fallback_destination,
        recommendedDepartureTime=leg.get("departure_time", {}).get("text")
        or _format_epoch_seconds(leg.get("departure_time", {}).get("value")),
        recommendedDepartureIso=_to_iso_from_epoch_seconds(leg.get("departure_time", {}).get("value")),
        estimatedArrivalTime=leg.get("arrival_time", {}).get("text")
        or _format_epoch_seconds(leg.get("arrival_time", {}).get("value")),
        estimatedArrivalIso=_to_iso_from_epoch_seconds(leg.get("arrival_time", {}).get("value")),
        durationText=leg.get("duration", {}).get("text"),
        durationSeconds=leg.get("duration", {}).get("value"),
        walkingDurationText=f"{walking_duration_seconds // 60} min" if walking_duration_seconds else None,
        walkingDurationSeconds=walking_duration_seconds or None,
        walkingDistanceText=f"{walking_distance_meters}m" if walking_distance_meters else None,
        walkingDistanceMeters=walking_distance_meters or None,
        transferCount=0,
        fareText=None,
        fareAmount=None,
        fareCurrency=None,
        routeSummary=_build_route_summary(steps),
        steps=steps,
    )


async def get_simple_route_plan(
    *, origin: str, destination: str, arrival_time_iso: str, mode: SurfaceTravelMode
) -> RoutePlan:
    logger.info(
        "google maps surface plan start mode=%s origin=%s destination=%s arrival_time_iso=%s",
        mode,
        origin,
        destination,
        arrival_time_iso,
    )
    resolved_origin = await resolve_location(origin, "origin", mode)
    resolved_destination = await resolve_location(destination, "destination", mode)
    target_arrival = _floor_to_minute(datetime.fromisoformat(arrival_time_iso.replace("Z", "+00:00")))
    route_mode = "bicycling" if mode == "bicycle" else "driving" if mode == "car" else "walking"
    _, leg = await _parse_directions_response(
        {
            "origin": resolved_origin.route_value,
            "destination": resolved_destination.route_value,
            "mode": route_mode,
            "departure_time": str(int(target_arrival.timestamp())),
            "language": "ja",
            "region": "jp",
        },
        mode,
        resolved_destination,
    )
    duration_seconds = leg.get("duration_in_traffic", {}).get("value") or leg.get("duration", {}).get("value") or 0
    recommended_departure = _floor_to_minute(target_arrival - timedelta(seconds=duration_seconds))
    plan = _build_route_plan(
        mode=mode,
        leg=leg,
        fallback_origin=resolved_origin.formatted_address,
        fallback_destination=resolved_destination.formatted_address,
    )
    plan.recommended_departure_time = recommended_departure.astimezone(JST).strftime("%H:%M")
    plan.recommended_departure_iso = recommended_departure.astimezone(UTC).isoformat()
    plan.estimated_arrival_time = target_arrival.astimezone(JST).strftime("%H:%M")
    plan.estimated_arrival_iso = target_arrival.astimezone(UTC).isoformat()
    plan.duration_text = leg.get("duration_in_traffic", {}).get("text") or leg.get("duration", {}).get("text")
    plan.duration_seconds = duration_seconds
    return plan
