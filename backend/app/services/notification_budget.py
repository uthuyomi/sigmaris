from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from app.services.supabase_rest import _get_client, _require_supabase_config
from app.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_MAX = 5


def _svc_headers() -> dict[str, str]:
    _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _get_max() -> int:
    """Read daily_notification_max from constitution doctrine."""
    try:
        from app.services.constitution import get_doctrine_value  # noqa: PLC0415
        val = await get_doctrine_value("daily_notification_max")
        if val:
            return int(val.split("件")[0].strip())
        return _DEFAULT_MAX
    except Exception:
        return _DEFAULT_MAX


async def get_daily_count() -> int:
    """Count notification-type decisions logged today (JST)."""
    try:
        today_jst = date.today().isoformat()
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/sigmaris_decision_log",
            headers={**_svc_headers(), "Prefer": "count=exact"},
            params={
                "decision_type": "eq.notification",
                "created_at": f"gte.{today_jst}T00:00:00+09:00",
                "select": "id",
            },
        )
        r.raise_for_status()
        content_range = r.headers.get("Content-Range", "")
        if "/" in content_range:
            total = content_range.split("/")[-1]
            if total.isdigit():
                return int(total)
        data = r.json()
        return len(data) if isinstance(data, list) else 0
    except Exception:
        logger.exception("notification_budget: failed to get_daily_count")
        return 0


async def can_notify() -> bool:
    """Return True if we are under the daily notification limit."""
    try:
        daily_max = await _get_max()
        count = await get_daily_count()
        ok = count < daily_max
        if not ok:
            logger.info("notification_budget: daily limit reached (%d/%d)", count, daily_max)
        return ok
    except Exception:
        logger.exception("notification_budget: failed to can_notify — allowing by default")
        return True


async def record_notification(
    *,
    title: str,
    reason: str | None = None,
    constitution_refs: list[str] | None = None,
    internal_state_snapshot: dict[str, Any] | None = None,
) -> str | None:
    """
    Record a notification decision in the decision log.
    Should be called AFTER can_notify() returns True.
    Returns the new row ID or None on failure.
    """
    try:
        from app.services.decision_log import log_decision  # noqa: PLC0415
        return await log_decision(
            decision_type="notification",
            title=title,
            reason=reason,
            constitution_refs=constitution_refs,
            internal_state_snapshot=internal_state_snapshot,
        )
    except Exception:
        logger.exception("notification_budget: failed to record_notification title=%s", title)
        return None


async def get_budget_status() -> dict[str, Any]:
    """Return current budget info as a dict."""
    try:
        daily_max = await _get_max()
        count = await get_daily_count()
        return {
            "used": count,
            "max": daily_max,
            "remaining": max(0, daily_max - count),
            "can_notify": count < daily_max,
            "date": date.today().isoformat(),
        }
    except Exception:
        logger.exception("notification_budget: failed to get_budget_status")
        return {
            "used": 0,
            "max": _DEFAULT_MAX,
            "remaining": _DEFAULT_MAX,
            "can_notify": True,
            "date": date.today().isoformat(),
        }
