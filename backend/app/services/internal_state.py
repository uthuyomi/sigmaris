# 用語注記(docs/sigmaris/glossary_curiosity.md「curiosity mood」):
# このモジュールの`curiosity`列は、curiosity_engine.py(好奇心リサーチ
# キュー、外部Web情報源の検索クエリ管理)ともdrive_system.KnowledgeGapDrive
# (旧CuriosityDrive、B3由来のユーザー知識ギャップ)とも無関係な、第3の
# 独立した概念——会話ターンごとに機械的に+0.01される、シグマリスの
# "雰囲気"を表すfloat値である。3つの詳細な違いは上記グロッサリ参照。

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_internal_state"

_VALID_INTERVENTION = frozenset({"low", "moderate", "high"})

# Cache the single-row state to avoid hitting DB on every conversation turn
_state_cache: dict[str, Any] | None = None
_state_cache_at: float = 0.0
_STATE_TTL = 300.0  # 5 minutes


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


_DEFAULTS: dict[str, Any] = {
    "confidence": 0.7,
    "concern": 0.0,
    "urgency": 0.0,
    "curiosity": 0.5,
    "stability": 0.8,
    "intervention_level": "moderate",
    "trust_in_context": 0.8,
}


async def get_internal_state() -> dict[str, Any]:
    """Return current internal state, from cache if fresh enough."""
    global _state_cache, _state_cache_at
    try:
        if _state_cache and (time.monotonic() - _state_cache_at < _STATE_TTL):
            return _state_cache

        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"limit": "1", "order": "updated_at.desc"},
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            _state_cache = data[0]
            _state_cache_at = time.monotonic()
            return _state_cache
        return dict(_DEFAULTS)
    except Exception:
        logger.exception("internal_state: failed to get_internal_state")
        return _state_cache if _state_cache else dict(_DEFAULTS)


async def update_internal_state(**kwargs: Any) -> bool:
    """
    Patch the internal state row with the provided fields.
    Only known float fields and intervention_level are accepted.
    """
    global _state_cache, _state_cache_at
    try:
        float_fields = {"confidence", "concern", "urgency", "curiosity", "stability", "trust_in_context"}
        payload: dict[str, Any] = {}

        for k, v in kwargs.items():
            if k in float_fields:
                payload[k] = max(0.0, min(1.0, float(v)))
            elif k == "intervention_level":
                if v in _VALID_INTERVENTION:
                    payload[k] = v
                else:
                    logger.warning("internal_state: invalid intervention_level=%s", v)

        if not payload:
            return False

        from datetime import datetime, timezone  # noqa: PLC0415
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()

        state = await get_internal_state()
        row_id = state.get("id") if state else None

        base_url, _ = _require_supabase_config()
        client = await _get_client()

        if row_id:
            r = await client.patch(
                f"{base_url}/rest/v1/{_TABLE}",
                headers=_svc_headers(prefer="return=representation"),
                params={"id": f"eq.{row_id}"},
                json=payload,
            )
        else:
            merged = {**_DEFAULTS, **payload}
            r = await client.post(
                f"{base_url}/rest/v1/{_TABLE}",
                headers=_svc_headers(prefer="return=representation"),
                json=merged,
            )

        r.raise_for_status()
        _state_cache_at = 0.0  # invalidate cache
        logger.info("internal_state: updated fields=%s", list(payload.keys()))
        return True
    except Exception:
        logger.exception("internal_state: failed to update_internal_state")
        return False


def get_intervention_level_from_state(state: dict[str, Any]) -> str:
    """Return 'low' | 'moderate' | 'high' derived from state values."""
    try:
        urgency = float(state.get("urgency", 0.0))
        concern = float(state.get("concern", 0.0))
        combined = (urgency + concern) / 2.0
        if combined >= 0.7:
            return "high"
        if combined >= 0.4:
            return "moderate"
        return "low"
    except Exception:
        return "moderate"


async def snapshot() -> dict[str, Any]:
    """Return a compact snapshot dict suitable for JSON storage in decision_log."""
    try:
        state = await get_internal_state()
        return {
            "confidence": state.get("confidence", 0.7),
            "concern": state.get("concern", 0.0),
            "urgency": state.get("urgency", 0.0),
            "curiosity": state.get("curiosity", 0.5),
            "stability": state.get("stability", 0.8),
            "intervention_level": state.get("intervention_level", "moderate"),
            "trust_in_context": state.get("trust_in_context", 0.8),
        }
    except Exception:
        logger.exception("internal_state: failed to snapshot")
        return dict(_DEFAULTS)
