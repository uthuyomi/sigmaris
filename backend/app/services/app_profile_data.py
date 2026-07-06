from __future__ import annotations

# 役割: ユーザープロフィールと設定データを扱う。

import hashlib
import time
from typing import Any

from app.services.supabase_rest import get_current_user, rest_select

# Phase BA2: get_profile_context() (auth/v1/user + profiles + saved_locations)
# used to be re-fetched from scratch on every call — measured at 3 separate
# call sites within a single /chat turn in
# docs/sigmaris/incident_response_latency_investigation.md (Phase A1's
# get_recent_messages_across_threads, chat.py's run_chat_completion/
# stream_chat_completion_ui, and app_chat_data.replace_chat_messages during
# persistence — plus several more call sites in this same file that all
# only need context["userId"], see list_chat_threads/create_chat_thread/
# etc. below). None of those call sites need up-to-the-second freshness —
# home address, saved locations, and ai tone only change when the user
# edits settings, which happens directly against Supabase from the
# frontend and never goes through this backend, so there is no write path
# here to hook a cache-invalidation call into. A short TTL is therefore the
# only available staleness control.
#
# 60s comfortably covers the ~36.4s worst-case full-turn duration measured
# in that investigation (so every duplicate call within one turn is a cache
# hit) while keeping the staleness window for a just-edited profile far
# below orchestrator/service.py's 300s TTL for the (much less volatile,
# LLM-derived) B-group reads.
#
# Cache key is a full SHA-256 of the jwt, not a prefix — see this task's
# report (docs/sigmaris/phase_ba2_report.md) for why keying by jwt[:20], as
# orchestrator/service.py's _cached_user_profile/_cached_active_trends
# already did, collides across every user on standard HS256-signed
# Supabase JWTs (the header alone is 36 base64 chars) and was fixed there
# in the same change as this one.
_CACHE_TTL_SECONDS = 60.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _cache_key(jwt: str) -> str:
    return hashlib.sha256(jwt.encode("utf-8")).hexdigest()


async def get_profile_context(jwt: str) -> dict[str, Any]:
    key = _cache_key(jwt)
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0] < _CACHE_TTL_SECONDS):
        return entry[1]
    result = await _fetch_profile_context(jwt)
    _cache[key] = (time.monotonic(), result)
    return result


async def _fetch_profile_context(jwt: str) -> dict[str, Any]:
    user = await get_current_user(jwt)
    user_id = user["id"]

    profile: dict[str, Any] | None = None
    try:
        profile = await rest_select(
            jwt,
            "profiles",
            {
                "select": "home_address,preferred_travel_mode,ai_tone,arrival_lead_minutes",
                "id": f"eq.{user_id}",
            },
            single=True,
        )
    except RuntimeError as error:
        response_text = str(error)
        if (
            "column profiles.ai_tone does not exist" not in response_text
            and 'column "ai_tone" does not exist' not in response_text
            and "column profiles.arrival_lead_minutes does not exist" not in response_text
            and 'column "arrival_lead_minutes" does not exist' not in response_text
        ):
            raise
        profile = await rest_select(
            jwt,
            "profiles",
            {
                "select": "home_address,preferred_travel_mode",
                "id": f"eq.{user_id}",
            },
            single=True,
        )

    locations = await rest_select(
        jwt,
        "saved_locations",
        {
            "select": "id,label,address,location_type,is_default_departure",
            "user_id": f"eq.{user_id}",
            "order": "is_default_departure.desc,created_at.asc",
        },
    )

    return {
        "userId": user_id,
        "homeAddress": profile.get("home_address") if profile else None,
        "preferredTravelMode": (
            (profile or {}).get("preferred_travel_mode")
            if (profile or {}).get("preferred_travel_mode") in {"bicycle", "car", "walk"}
            else "car"
        ),
        "aiTone": (profile or {}).get("ai_tone") or "default",
        "arrivalLeadMinutes": (profile or {}).get("arrival_lead_minutes") or 10,
        "savedLocations": [
            {
                "id": item["id"],
                "label": item["label"],
                "address": item["address"],
                "locationType": item["location_type"],
                "isDefaultDeparture": item["is_default_departure"],
            }
            for item in (locations or [])
        ],
    }


