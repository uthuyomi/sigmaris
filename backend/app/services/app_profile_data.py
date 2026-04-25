from __future__ import annotations

# 役割: ユーザープロフィールと設定データを扱う。

from typing import Any

from app.services.supabase_rest import get_current_user, rest_select


async def get_profile_context(jwt: str) -> dict[str, Any]:
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


