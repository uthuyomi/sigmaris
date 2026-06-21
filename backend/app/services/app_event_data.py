from __future__ import annotations

# 役割: アプリ内予定データの保存、検索、競合確認を扱う。

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.audit_log import AuditContext
from app.services.supabase_rest import (
    get_current_user,
    rest_delete,
    rest_insert,
    rest_rpc,
    rest_select,
    rest_update,
)

logger = logging.getLogger(__name__)
MAX_BULK_EVENT_INSERT = 100
EVENT_SELECT_COLUMNS = (
    "id,user_id,title,description,location_text,starts_at,ends_at,source_type,"
    "external_event_id,status,calendar_connection_id,metadata"
)


def _normalize_event_time(value: str) -> str:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _event_match_key(event: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(event.get("title") or "").strip(),
        _normalize_event_time(str(event["starts_at"])),
        _normalize_event_time(str(event["ends_at"])),
    )


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
    audit_ctx: AuditContext | None = None,
) -> dict[str, Any]:
    user = await get_current_user(jwt)
    event_data = {
        "user_id": user["id"],
        "title": title,
        "description": description,
        "location_text": location_text,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "source_type": source_type,
        "external_event_id": external_event_id,
        "metadata": metadata or {},
    }
    if audit_ctx is None:
        return await rest_insert(jwt, "events", event_data, single=True)
    return await rest_rpc(jwt, "create_event_with_audit", {
        "p_event": event_data,
        "p_audit": audit_ctx.to_jsonb(),
    })


async def create_events(
    jwt: str,
    events: list[dict[str, Any]],
    audit_ctx: AuditContext | None = None,
) -> list[dict[str, Any]]:
    if not events:
        return []
    if len(events) > MAX_BULK_EVENT_INSERT:
        raise ValueError(f"Too many events to create at once: {len(events)} > {MAX_BULK_EVENT_INSERT}")

    user = await get_current_user(jwt)
    from_iso = min(str(event["starts_at"]) for event in events)
    to_iso = max(str(event["ends_at"]) for event in events)
    existing_rows = await rest_select(
        jwt,
        "events",
        {
            "select": EVENT_SELECT_COLUMNS,
            "user_id": f"eq.{user['id']}",
            "status": "neq.cancelled",
            "starts_at": f"gte.{from_iso}",
            "ends_at": f"lte.{to_iso}",
            "limit": "1000",
        },
    )
    existing_by_key = {
        _event_match_key(row): row
        for row in (existing_rows or [])
        if row.get("starts_at") and row.get("ends_at")
    }

    ordered_results: list[dict[str, Any] | None] = [None] * len(events)
    events_to_insert: list[tuple[int, dict[str, Any]]] = []
    for index, event in enumerate(events):
        key = _event_match_key(event)
        existing = existing_by_key.get(key)
        if existing:
            ordered_results[index] = existing
        else:
            events_to_insert.append((index, event))

    payload = [
        {
            "user_id": user["id"],
            "title": event["title"],
            "description": event.get("description"),
            "location_text": event.get("location_text"),
            "starts_at": event["starts_at"],
            "ends_at": event["ends_at"],
            "source_type": event.get("source_type") or "manual",
            "external_event_id": event.get("external_event_id"),
            "calendar_connection_id": event.get("calendar_connection_id"),
            "metadata": event.get("metadata") or {},
        }
        for _, event in events_to_insert
    ]
    logger.info(
        "creating app events in bulk requested=%s existing=%s inserting=%s",
        len(events),
        len(events) - len(events_to_insert),
        len(payload),
    )
    if payload and audit_ctx is not None:
        raw = await rest_rpc(jwt, "create_events_with_audit", {
            "p_events": payload,
            "p_audit": audit_ctx.to_jsonb(),
        })
        created = raw if isinstance(raw, list) else []
    elif payload:
        created = await rest_insert(jwt, "events", payload)
    else:
        created = []
    for (index, _), created_row in zip(events_to_insert, created or []):
        ordered_results[index] = created_row

    missing_indexes = [
        index for index, row in enumerate(ordered_results)
        if row is None
    ]
    if missing_indexes:
        logger.warning("app event bulk create returned fewer rows missing_indexes=%s", missing_indexes)
        ordered_results = [row for row in ordered_results if row is not None]

    logger.info("created app events in bulk inserted=%s returned=%s", len(created or []), len(ordered_results))
    return [row for row in ordered_results if row is not None]


async def update_event_external_link(
    jwt: str,
    *,
    event_id: str,
    external_event_id: str | None,
    calendar_connection_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    audit_ctx: AuditContext | None = None,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {
        "external_event_id": external_event_id,
        "metadata": metadata or {},
    }
    if calendar_connection_id is not None:
        payload["calendar_connection_id"] = calendar_connection_id
    if audit_ctx is not None:
        return await rest_rpc(jwt, "update_event_external_link_with_audit", {
            "p_event_id": event_id,
            "p_payload": payload,
            "p_audit": audit_ctx.to_jsonb(),
        })
    rows = await rest_update(jwt, "events", payload, {"id": f"eq.{event_id}"})
    return rows[0] if rows else None


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


