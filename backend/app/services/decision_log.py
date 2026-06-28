from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_decision_log"

_VALID_TYPES = frozenset({"proposal", "refusal", "notification", "action"})

_ANALYZE_SYSTEM = "あなたはシグマリスの意思決定分析システムです。過去の判断パターンを分析し、改善点を日本語で返してください。必ず有効なJSONのみを返してください。"

_ANALYZE_PROMPT = """以下のシグマリスの意思決定ログを分析してください。

## 直近の決定（{n}件）
{decisions}

---
以下のJSONを出力してください:
{{
  "common_patterns": ["よく見られるパターン1", "パターン2"],
  "proposal_rate": 0.0,
  "refusal_rate": 0.0,
  "improvement_suggestions": ["改善提案1", "改善提案2"],
  "notes": "全体的な傾向メモ"
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


async def log_decision(
    *,
    decision_type: str,
    title: str,
    reason: str | None = None,
    constitution_refs: list[str] | None = None,
    memory_refs: list[str] | None = None,
    experience_refs: list[str] | None = None,
    internal_state_snapshot: dict[str, Any] | None = None,
    outcome: str | None = None,
) -> str | None:
    """Insert a decision log entry. Returns new row ID or None on failure."""
    try:
        if decision_type not in _VALID_TYPES:
            logger.warning("decision_log: invalid type=%s", decision_type)
            return None

        payload: dict[str, Any] = {
            "decision_type": decision_type,
            "title": title,
            "constitution_refs": constitution_refs or [],
            "memory_refs": memory_refs or [],
            "experience_refs": experience_refs or [],
            "internal_state_snapshot": internal_state_snapshot or {},
        }
        if reason is not None:
            payload["reason"] = reason
        if outcome is not None:
            payload["outcome"] = outcome

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
            logger.info("decision_log: logged %s title=%s id=%s", decision_type, title[:60], rid)
            return rid
        return None
    except Exception:
        logger.exception("decision_log: failed to log_decision type=%s title=%s", decision_type, title[:60])
        return None


async def update_outcome(decision_id: str, outcome: str) -> bool:
    """Set the outcome of a previously logged decision."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            params={"id": f"eq.{decision_id}"},
            json={"outcome": outcome},
        )
        r.raise_for_status()
        logger.info("decision_log: updated outcome id=%s", decision_id)
        return True
    except Exception:
        logger.exception("decision_log: failed to update_outcome id=%s", decision_id)
        return False


async def get_recent_decisions(
    limit: int = 30,
    *,
    decision_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent decision log entries."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        params: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
        if decision_type:
            params["decision_type"] = f"eq.{decision_type}"
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params=params,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("decision_log: failed to get_recent_decisions")
        return []


async def analyze_decision_patterns() -> dict[str, Any] | None:
    """Sunday 4:30 AM scheduled: LLM analysis of recent decision patterns."""
    try:
        decisions = await get_recent_decisions(limit=50)
        if not decisions:
            logger.info("decision_log: no decisions to analyze")
            return None

        lines = []
        type_counts: dict[str, int] = {}
        for d in decisions[:30]:
            dt = d.get("decision_type", "")
            type_counts[dt] = type_counts.get(dt, 0) + 1
            lines.append(
                f"[{dt}] {d.get('title', '')} reason={d.get('reason', 'N/A')[:80]}"
            )

        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": _ANALYZE_SYSTEM},
                {"role": "user", "content": _ANALYZE_PROMPT.format(
                    n=len(decisions),
                    decisions="\n".join(lines),
                )},
            ],
            temperature=0.3,
            max_tokens=512,
            json_mode=True,
        )
        analysis = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(analysis, dict):
            return None

        analysis["type_counts"] = type_counts
        total = len(decisions)
        analysis["proposal_rate"] = type_counts.get("proposal", 0) / total if total else 0.0
        analysis["refusal_rate"] = type_counts.get("refusal", 0) / total if total else 0.0
        logger.info("decision_log: pattern analysis done")
        return analysis
    except Exception:
        logger.exception("decision_log: failed to analyze_decision_patterns")
        return None
