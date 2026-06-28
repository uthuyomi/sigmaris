from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_experience"

_VALID_TYPES = frozenset({"success", "failure", "unresolved"})
_VALID_CATEGORIES = frozenset({"proposal", "reflection", "research", "interaction", "prediction"})

_ANALYZE_SYSTEM = "あなたはシグマリスの自己分析システムです。経験パターンを分析し、改善点を日本語で簡潔に返してください。必ず有効なJSONのみを返してください。"

_ANALYZE_PROMPT = """以下のシグマリスの経験記録を分析し、パターンと改善点を抽出してください。

## 直近の経験（{n}件）
{experiences}

---
以下のJSONを出力してください:
{{
  "success_patterns": ["成功パターン1", "成功パターン2"],
  "failure_patterns": ["失敗パターン1", "失敗パターン2"],
  "improvement_suggestions": ["改善提案1", "改善提案2"],
  "adoption_rate_avg": 0.0,
  "confidence_delta_avg": 0.0
}}"""


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


async def record_experience(
    *,
    experience_type: str,
    category: str,
    title: str,
    description: str | None = None,
    context: dict[str, Any] | None = None,
    outcome: str | None = None,
    lesson: str | None = None,
    adoption_rate: float | None = None,
    confidence_delta: float = 0.0,
    related_fact_ids: list[str] | None = None,
) -> str | None:
    """Insert a new experience record. Returns the created row ID or None."""
    try:
        if experience_type not in _VALID_TYPES:
            logger.warning("experience_layer: invalid type=%s", experience_type)
            return None
        if category not in _VALID_CATEGORIES:
            logger.warning("experience_layer: invalid category=%s", category)
            return None

        payload: dict[str, Any] = {
            "experience_type": experience_type,
            "category": category,
            "title": title,
            "confidence_delta": confidence_delta,
        }
        if description is not None:
            payload["description"] = description
        if context is not None:
            payload["context"] = context
        if outcome is not None:
            payload["outcome"] = outcome
        if lesson is not None:
            payload["lesson"] = lesson
        if adoption_rate is not None:
            payload["adoption_rate"] = max(0.0, min(1.0, adoption_rate))
        if related_fact_ids is not None:
            payload["related_fact_ids"] = related_fact_ids

        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.post(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            json=payload,
        )
        r.raise_for_status()
        rows = r.json()
        if isinstance(rows, list) and rows:
            rid = rows[0].get("id")
            logger.info("experience_layer: recorded %s/%s id=%s", experience_type, category, rid)
            return rid
        return None
    except Exception:
        logger.exception("experience_layer: failed to record_experience title=%s", title)
        return None


async def get_recent_experiences(
    limit: int = 30,
    *,
    experience_type: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent experience rows, optionally filtered."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        params: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
        if experience_type:
            params["experience_type"] = f"eq.{experience_type}"
        if category:
            params["category"] = f"eq.{category}"
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params=params,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("experience_layer: failed to get_recent_experiences")
        return []


async def analyze_patterns() -> dict[str, Any] | None:
    """Weekly scheduled: LLM analysis of recent experience patterns."""
    try:
        experiences = await get_recent_experiences(limit=50)
        if not experiences:
            logger.info("experience_layer: no experiences to analyze")
            return None

        summary_lines = []
        for e in experiences[:30]:
            summary_lines.append(
                f"[{e.get('experience_type')}][{e.get('category')}] {e.get('title')} "
                f"outcome={e.get('outcome', 'N/A')} lesson={e.get('lesson', 'N/A')}"
            )
        experiences_text = "\n".join(summary_lines)

        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": _ANALYZE_SYSTEM},
                {"role": "user", "content": _ANALYZE_PROMPT.format(
                    n=len(experiences),
                    experiences=experiences_text,
                )},
            ],
            temperature=0.3,
            max_tokens=512,
            json_mode=True,
        )
        analysis = json.loads(raw) if isinstance(raw, str) else raw
        logger.info("experience_layer: pattern analysis done patterns=%s", list(analysis.keys()))
        return analysis if isinstance(analysis, dict) else None
    except Exception:
        logger.exception("experience_layer: failed to analyze_patterns")
        return None


async def mark_resolved(experience_id: str, *, outcome: str, lesson: str | None = None) -> bool:
    """Update an unresolved experience to success or failure."""
    try:
        payload: dict[str, Any] = {"outcome": outcome, "experience_type": "success"}
        if lesson:
            payload["lesson"] = lesson
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            params={"id": f"eq.{experience_id}"},
            json=payload,
        )
        r.raise_for_status()
        logger.info("experience_layer: resolved id=%s", experience_id)
        return True
    except Exception:
        logger.exception("experience_layer: failed to mark_resolved id=%s", experience_id)
        return False
