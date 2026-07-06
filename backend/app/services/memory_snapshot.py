from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.services.decision_log import get_active_preference_patterns
from app.services.goal_alignment import get_active_goal_alignment_flags
from app.services.knowledge_graph import get_entities_and_relations
from app.services.supabase_rest import _get_client, _require_supabase_config
from app.services.topic_tracker import get_current_and_previous_topic

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_user_snapshot"


def _svc_headers(*, prefer: str | None = None) -> dict[str, str]:
    _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    headers: dict[str, str] = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def empty_memory_snapshot(user_id: str | None = None) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "preference_patterns": [],
        "topic_state": {"current": None, "previous": None},
        "goal_alignment_flags": [],
        "entities": [],
        "relations": [],
        "generated_at": None,
    }


async def build_memory_snapshot_payload(user_id: str) -> dict[str, Any]:
    """Collect the latest B6/B9/B14/B16 outputs without changing extraction logic."""
    preference_patterns = await get_active_preference_patterns(limit=5)
    current_topic, previous_topic = await get_current_and_previous_topic()
    goal_alignment_flags = await get_active_goal_alignment_flags(limit=1)
    entities, relations = await get_entities_and_relations()

    return {
        "user_id": user_id,
        "preference_patterns": preference_patterns,
        "topic_state": {"current": current_topic, "previous": previous_topic},
        "goal_alignment_flags": goal_alignment_flags,
        "entities": entities,
        "relations": relations,
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def write_memory_snapshot(payload: dict[str, Any]) -> dict[str, Any] | None:
    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("memory snapshot payload requires user_id")

    row = {
        "user_id": user_id,
        "preference_patterns": payload.get("preference_patterns") or [],
        "topic_state": payload.get("topic_state") or {"current": None, "previous": None},
        "goal_alignment_flags": payload.get("goal_alignment_flags") or [],
        "entities": payload.get("entities") or [],
        "relations": payload.get("relations") or [],
        "generated_at": payload.get("generated_at") or datetime.now(UTC).isoformat(),
    }

    base_url, _ = _require_supabase_config()
    client = await _get_client()
    resp = await client.post(
        f"{base_url}/rest/v1/{_TABLE}",
        headers=_svc_headers(prefer="resolution=merge-duplicates,return=representation"),
        params={"on_conflict": "user_id"},
        json=row,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else None


async def generate_memory_snapshot(user_id: str) -> dict[str, Any]:
    """Weekly batch entry point: aggregate existing B6/B9/B14/B16 outputs."""
    result: dict[str, Any] = {
        "user_id": user_id,
        "preferences": 0,
        "has_current_topic": False,
        "goal_flags": 0,
        "entities": 0,
        "relations": 0,
        "stored": False,
        "errors": 0,
    }
    try:
        payload = await build_memory_snapshot_payload(user_id)
        topic_state = payload.get("topic_state") if isinstance(payload.get("topic_state"), dict) else {}
        result.update(
            {
                "preferences": len(payload.get("preference_patterns") or []),
                "has_current_topic": bool(topic_state.get("current")),
                "goal_flags": len(payload.get("goal_alignment_flags") or []),
                "entities": len(payload.get("entities") or []),
                "relations": len(payload.get("relations") or []),
            }
        )
        stored = await write_memory_snapshot(payload)
        result["stored"] = bool(stored)
        logger.info("memory_snapshot: generated user_id=%s result=%s", user_id, result)
        return result
    except Exception:
        logger.exception("memory_snapshot: failed to generate user_id=%s", user_id)
        result["errors"] += 1
        return result


async def get_memory_snapshot(user_id: str) -> dict[str, Any]:
    """Return the latest precomputed snapshot for response-time context injection."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        resp = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"user_id": f"eq.{user_id}", "limit": "1"},
        )
        resp.raise_for_status()
        rows = resp.json()
        if isinstance(rows, list) and rows:
            row = rows[0]
            return {
                "user_id": row.get("user_id"),
                "preference_patterns": row.get("preference_patterns") or [],
                "topic_state": row.get("topic_state") or {"current": None, "previous": None},
                "goal_alignment_flags": row.get("goal_alignment_flags") or [],
                "entities": row.get("entities") or [],
                "relations": row.get("relations") or [],
                "generated_at": row.get("generated_at"),
            }
        return empty_memory_snapshot(user_id)
    except Exception:
        logger.exception("memory_snapshot: failed to get user_id=%s", user_id)
        return empty_memory_snapshot(user_id)
