from __future__ import annotations

# 役割: Google Maps 連携の共通処理とエラー処理を扱う。

from dataclasses import dataclass
from datetime import datetime
from html import unescape
import logging
import re
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.schemas.mobility import RouteLookupCandidate, RouteLookupResolution, TravelMode

JST = ZoneInfo("Asia/Tokyo")
UTC = ZoneInfo("UTC")
COORDINATE_PATTERN = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*$")
logger = logging.getLogger(__name__)


class RouteLookupError(Exception):
    def __init__(
        self,
        message: str,
        *,
        mode: TravelMode,
        status: str | None = None,
        resolution: RouteLookupResolution | None = None,
    ) -> None:
        super().__init__(message)
        self.mode = mode
        self.status = status
        self.resolution = resolution


@dataclass
class ResolvedLocation:
    route_value: str
    formatted_address: str
    latitude: float
    longitude: float
    candidates: list[RouteLookupCandidate]


def _require_maps_key() -> str:
    if not settings.google_maps_api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not set for backend.")
    return settings.google_maps_api_key


def _format_epoch_seconds(epoch_seconds: int | None) -> str | None:
    if not epoch_seconds:
        return None
    return datetime.fromtimestamp(epoch_seconds, JST).strftime("%H:%M")


def _to_iso_from_epoch_seconds(epoch_seconds: int | None) -> str | None:
    if not epoch_seconds:
        return None
    return datetime.fromtimestamp(epoch_seconds, JST).astimezone(UTC).isoformat()


def _floor_to_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _sum_step_metric(steps: list[dict], *, field: str, travel_mode: str) -> int:
    return sum(
        int(step.get(field, {}).get("value") or 0)
        for step in steps
        if step.get("travel_mode") == travel_mode
    )


def _build_route_lookup_error(status: str | None, error_message: str | None) -> str:
    if error_message:
        return f"{error_message} (Google Maps status: {status or 'UNKNOWN'})"
    if status == "ZERO_RESULTS":
        return "No route was found for this origin and destination."
    if status == "NOT_FOUND":
        return "Google Maps could not resolve the origin or destination into a valid place."
    if status == "REQUEST_DENIED":
        return "Google Maps request was denied. Check the API key and enabled APIs."
    if status == "OVER_QUERY_LIMIT":
        return "Google Maps query limit was reached."
    if status == "INVALID_REQUEST":
        return "Google Maps request was invalid. Check the origin, destination, and arrival time."
    return f"Google Maps route lookup failed. (status: {status or 'UNKNOWN'})"


async def _google_get(url: str, params: dict[str, str]) -> dict:
    key = _require_maps_key()
    redacted_params = {**params, "key": "***"}
    logger.info("google maps request url=%s params=%s", url, redacted_params)
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, params={**params, "key": key})
        response.raise_for_status()
        data = response.json()
        logger.info(
            "google maps response url=%s http_status=%s status=%s",
            url,
            response.status_code,
            data.get("status"),
        )
        return data


