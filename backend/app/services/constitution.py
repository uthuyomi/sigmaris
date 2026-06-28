from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_constitution"
_cache: list[dict[str, Any]] = []
_cache_at: float = 0.0
_CACHE_TTL = 600.0  # 10 minutes


def _svc_headers(*, prefer: str | None = None) -> dict[str, str]:
    _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    h: dict[str, str] = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


async def _fetch_all() -> list[dict[str, Any]]:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.get(
        f"{base_url}/rest/v1/{_TABLE}",
        headers=_svc_headers(),
        params={"order": "layer.asc,key.asc"},
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


async def load_constitution(*, force: bool = False) -> list[dict[str, Any]]:
    """Return all constitution rows, cached for 10 minutes."""
    global _cache, _cache_at
    try:
        if not force and _cache and (time.monotonic() - _cache_at < _CACHE_TTL):
            return _cache
        rows = await _fetch_all()
        _cache = rows
        _cache_at = time.monotonic()
        return rows
    except Exception:
        logger.exception("constitution: failed to load")
        return _cache  # return stale on failure


async def get_core_values() -> list[dict[str, Any]]:
    """Return immutable core value rows (layer='core')."""
    try:
        rows = await load_constitution()
        return [r for r in rows if r.get("layer") == "core"]
    except Exception:
        logger.exception("constitution: failed to get_core_values")
        return []


async def get_doctrine() -> list[dict[str, Any]]:
    """Return operational doctrine rows (layer='doctrine')."""
    try:
        rows = await load_constitution()
        return [r for r in rows if r.get("layer") == "doctrine"]
    except Exception:
        logger.exception("constitution: failed to get_doctrine")
        return []


async def get_doctrine_value(key: str) -> str | None:
    """Return value of a single doctrine key, or None."""
    try:
        rows = await get_doctrine()
        for r in rows:
            if r.get("key") == key:
                return r.get("value")
        return None
    except Exception:
        logger.exception("constitution: failed to get_doctrine_value key=%s", key)
        return None


async def build_constitution_context() -> str:
    """Return a compact text block for injection into system prompts."""
    try:
        values = await get_core_values()
        doctrine = await get_doctrine()
        lines = ["[シグマリス基本原則]"]
        for r in values:
            lines.append(f"・{r.get('value', '')}")
        if doctrine:
            lines.append("[行動指針]")
            for r in doctrine:
                lines.append(f"・{r.get('value', '')}")
        return "\n".join(lines)
    except Exception:
        logger.exception("constitution: failed to build_constitution_context")
        return ""


async def update_doctrine(key: str, value: str) -> bool:
    """Update a mutable doctrine value. Returns True on success."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            params={"layer": "eq.doctrine", "key": f"eq.{key}", "is_mutable": "eq.true"},
            json={"value": value},
        )
        r.raise_for_status()
        global _cache_at
        _cache_at = 0.0  # invalidate cache
        logger.info("constitution: updated doctrine key=%s", key)
        return True
    except Exception:
        logger.exception("constitution: failed to update doctrine key=%s", key)
        return False
