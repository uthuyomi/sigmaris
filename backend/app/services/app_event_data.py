from __future__ import annotations

# 役割: アプリ内予定データの保存、検索、競合確認を扱う。

from typing import Any

from app.services.supabase_rest import get_current_user, rest_delete, rest_insert, rest_select


async def search_events(
    jwt: str,
    *,
    query: str,
    from_iso: str | None = None,
    to_iso: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    params = {
        "select": "id,title,description,location_text,starts_at,ends_at,source_type,external_event_id",
        "status": "neq.cancelled",
        "order": "starts_at.asc",
        "limit": str(limit),
        "or": f"(title.ilike.%{query}%,location_text.ilike.%{query}%,description.ilike.%{query}%)",
    }
    filters = []
    if from_iso:
        filters.append(f"starts_at.gte.{from_iso}")
    if to_iso:
        filters.append(f"starts_at.lt.{to_iso}")
    if filters:
        params["and"] = f"({','.join(filters)})"

    rows = await rest_select(jwt, "events", params)
    return rows or []


async def list_events(
    jwt: str,
    *,
    from_iso: str,
    to_iso: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params = {
        "select": "id,title,description,location_text,starts_at,ends_at,source_type,external_event_id",
        "status": "neq.cancelled",
        "starts_at": f"gte.{from_iso}",
        "ends_at": f"lt.{to_iso}",
        "order": "starts_at.asc",
        "limit": str(limit),
    }

    rows = await rest_select(jwt, "events", params)
    return rows or []


async def get_event_by_id(jwt: str, event_id: str) -> dict[str, Any] | None:
    return await rest_select(
        jwt,
        "events",
        {
            "select": "id,user_id,title,description,location_text,starts_at,ends_at,source_type,external_event_id,status,calendar_connection_id,metadata",
            "id": f"eq.{event_id}",
        },
        single=True,
    )


async def list_conflicting_events(
    jwt: str,
    *,
    starts_at: str,
    ends_at: str,
    exclude_event_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    user = await get_current_user(jwt)
    rows = await rest_select(
        jwt,
        "events",
        {
            "select": "id,title,starts_at,ends_at,location_text",
            "user_id": f"eq.{user['id']}",
            "status": "neq.cancelled",
            "starts_at": f"lt.{ends_at}",
            "ends_at": f"gt.{starts_at}",
            "order": "starts_at.asc",
        },
    )
    return [
        row for row in (rows or [])
        if row["id"] not in (exclude_event_ids or [])
    ]


async def create_event(
    jwt: str,
    *,
    title: str,
    starts_at: str,
    ends_at: str,
    description: str | None = None,
    location_text: str | None = None,
    source_type: str = "manual",
    external_event_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user = await get_current_user(jwt)
    return await rest_insert(
        jwt,
        "events",
        {
            "user_id": user["id"],
            "title": title,
            "description": description,
            "location_text": location_text,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "source_type": source_type,
            "external_event_id": external_event_id,
            "metadata": metadata or {},
        },
        single=True,
    )


async def replace_travel_plan(
    jwt: str,
    *,
    event_id: str,
    origin_label: str,
    origin_address: str,
    destination_label: str,
    destination_address: str,
    travel_mode: str,
    recommended_departure_at: str | None,
    estimated_arrival_at: str | None,
    duration_minutes: int | None,
    route_summary: str | None,
    route_steps: list[dict[str, Any]],
    fare_text: str | None = None,
    fare_amount: float | None = None,
    fare_currency: str | None = None,
    transfer_count: int | None = None,
    walking_distance_meters: int | None = None,
    walking_duration_minutes: int | None = None,
    selected_candidate: dict[str, Any] | None = None,
) -> None:
    await rest_delete(jwt, "event_travel_plans", {"event_id": f"eq.{event_id}"})
    await rest_insert(
        jwt,
        "event_travel_plans",
        {
            "event_id": event_id,
            "origin_label": origin_label,
            "origin_address": origin_address,
            "destination_label": destination_label,
            "destination_address": destination_address,
            "travel_mode": travel_mode,
            "recommended_departure_at": recommended_departure_at,
            "estimated_arrival_at": estimated_arrival_at,
            "duration_minutes": duration_minutes,
            "route_summary": route_summary,
            "route_steps": route_steps,
            "fare_text": fare_text,
            "fare_amount": fare_amount,
            "fare_currency": fare_currency,
            "transfer_count": transfer_count,
            "walking_distance_meters": walking_distance_meters,
            "walking_duration_minutes": walking_duration_minutes,
            "selected_candidate": selected_candidate or {},
        },
    )


