from __future__ import annotations

# 役割: ユーザー事実記憶層の読み書きを提供する。

from typing import Any

from app.services.supabase_rest import rest_rpc, rest_select

_PROFILE_SCALAR_FIELDS = [
    "name", "birthdate", "prefecture", "city", "address_detail",
    "email", "occupation", "income_range",
]
_PROFILE_JSONB_FIELDS = [
    "lifestyle_notes", "devices", "preferences", "goals", "values", "communication_settings",
]


async def get_user_profile(jwt: str) -> dict[str, Any] | None:
    """Returns the single user_fact_profile row, or None if it does not exist yet."""
    return await rest_select(jwt, "user_fact_profile", {"select": "*"}, single=True)


async def get_fact_items(
    jwt: str,
    *,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Returns all user_fact_items, optionally filtered by category."""
    params: dict[str, str] = {"select": "*", "order": "category.asc,key.asc"}
    if category:
        params["category"] = f"eq.{category}"
    result = await rest_select(jwt, "user_fact_items", params)
    return result if isinstance(result, list) else []


async def upsert_fact_item(
    jwt: str,
    *,
    category: str,
    key: str,
    value: str | None,
    confidence: float = 1.0,
    source: str = "manual",
    reason: str = "",
    notes: str | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Atomically upserts one fact item and appends a history row via RPC."""
    return await rest_rpc(jwt, "upsert_fact_item", {
        "p_category": category,
        "p_key": key,
        "p_value": value,
        "p_confidence": confidence,
        "p_source": source,
        "p_reason": reason,
        "p_notes": notes,
        "p_expires_at": expires_at,
    })


async def get_null_fields(jwt: str) -> list[dict[str, str]]:
    """Returns profile fields and fact items where value is null — candidates for Sigmaris to fill."""
    profile = await get_user_profile(jwt)
    items = await get_fact_items(jwt)
    missing: list[dict[str, str]] = []

    if profile is None:
        for field in _PROFILE_SCALAR_FIELDS + _PROFILE_JSONB_FIELDS:
            missing.append({"source": "user_fact_profile", "key": field})
    else:
        for field in _PROFILE_SCALAR_FIELDS + _PROFILE_JSONB_FIELDS:
            if profile.get(field) is None:
                missing.append({"source": "user_fact_profile", "key": field})

    for item in items:
        if item.get("value") is None:
            missing.append({
                "source": "user_fact_items",
                "category": item.get("category", ""),
                "key": item.get("key", ""),
                "id": item.get("id", ""),
            })

    return missing


def build_profile_context(profile: dict[str, Any] | None) -> str | None:
    """Formats a compact profile summary for injection into the schedule agent's system prompt."""
    if not profile:
        return None

    lines: list[str] = ["[ユーザーコンテキスト]"]

    name = profile.get("name")
    comm = profile.get("communication_settings")
    nickname = comm.get("nickname") if isinstance(comm, dict) else None
    if name:
        call = f"（呼称: {nickname}）" if nickname else ""
        lines.append(f"氏名: {name}{call}")

    parts = [profile.get("prefecture"), profile.get("city")]
    location = " ".join(p for p in parts if p)
    if location:
        lines.append(f"居住地: {location}")

    if profile.get("occupation"):
        lines.append(f"職業: {profile['occupation']}")

    env_prefs = profile.get("preferences")
    if isinstance(env_prefs, dict) and env_prefs.get("hobbies"):
        hobbies = env_prefs["hobbies"]
        if isinstance(hobbies, list):
            lines.append(f"趣味: {', '.join(hobbies[:5])}")

    goals = profile.get("goals")
    if isinstance(goals, dict):
        short = goals.get("short_term")
        if isinstance(short, list) and short:
            lines.append(f"直近の目標: {', '.join(short[:3])}")

    if isinstance(comm, dict) and comm.get("tone"):
        lines.append(f"コミュニケーション: {comm['tone']}")

    if len(lines) == 1:
        return None
    return "\n".join(lines)


def extract_call_name(profile: dict[str, Any] | None) -> str | None:
    """Returns the user's preferred call name from communication_settings.nickname."""
    if not profile:
        return None
    comm = profile.get("communication_settings")
    if isinstance(comm, dict):
        nickname = comm.get("nickname")
        if isinstance(nickname, str) and nickname.strip():
            return nickname.strip()
    return None
