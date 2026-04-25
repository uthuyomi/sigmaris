from __future__ import annotations

# 役割: Google Maps で出発地と目的地を解決する。

from app.schemas.mobility import RouteLookupCandidate, RouteLookupResolution, TravelMode
from app.services.google_maps_core import (
    COORDINATE_PATTERN,
    RouteLookupError,
    ResolvedLocation,
    _google_get,
    logger,
)


async def resolve_location(query: str, target: str, mode: TravelMode) -> ResolvedLocation:
    logger.info("google maps resolve_location target=%s mode=%s query=%s", target, mode, query)
    if COORDINATE_PATTERN.match(query):
        latitude, longitude = [float(value.strip()) for value in query.split(",")]
        candidate = RouteLookupCandidate(
            formattedAddress=f"{latitude},{longitude}",
            latitude=latitude,
            longitude=longitude,
        )
        return ResolvedLocation(
            route_value=f"{latitude},{longitude}",
            formatted_address=f"{latitude},{longitude}",
            latitude=latitude,
            longitude=longitude,
            candidates=[candidate],
        )

    data = await _google_get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        {
            "address": query,
            "language": "ja",
            "region": "jp",
        },
    )
    candidates = [
        RouteLookupCandidate(
            formattedAddress=result["formatted_address"],
            latitude=result["geometry"]["location"]["lat"],
            longitude=result["geometry"]["location"]["lng"],
            placeId=result.get("place_id"),
        )
        for result in data.get("results", [])
        if result.get("formatted_address")
        and result.get("geometry", {}).get("location", {}).get("lat") is not None
        and result.get("geometry", {}).get("location", {}).get("lng") is not None
    ]
    if data.get("status") != "OK" or not candidates:
        message = (
            "Could not resolve the origin into a valid place."
            if target == "origin"
            else "Could not resolve the destination into a valid place."
        )
        raise RouteLookupError(
            message,
            mode=mode,
            status=data.get("status"),
            resolution=RouteLookupResolution(target=target, query=query, candidates=candidates),
        )

    top = candidates[0]
    return ResolvedLocation(
        route_value=top.formatted_address,
        formatted_address=top.formatted_address,
        latitude=top.latitude,
        longitude=top.longitude,
        candidates=candidates,
    )


