from __future__ import annotations

from urllib.parse import urlencode


GOOGLE_MAPS_TRAVEL_MODES = {
    "bicycle": "bicycling",
    "car": "driving",
    "walk": "walking",
}


def build_google_maps_directions_url(
    *,
    origin: str | None,
    destination: str | None,
    travel_mode: str | None,
) -> str:
    params = {"api": "1"}
    if origin:
        params["origin"] = origin
    if destination:
        params["destination"] = destination
    if travel_mode in GOOGLE_MAPS_TRAVEL_MODES:
        params["travelmode"] = GOOGLE_MAPS_TRAVEL_MODES[travel_mode]

    return f"https://www.google.com/maps/dir/?{urlencode(params)}"
