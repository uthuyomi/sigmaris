from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_curiosity_queue"

_VALID_SOURCES = frozenset({"stale_fact", "unresolved_experience", "trend", "self_model_gap"})

_GENERATE_SYSTEM = "あなたはシグマリスの好奇心エンジンです。ユーザーの状況から探索すべき問いを日本語で生成してください。必ず有効なJSONのみを返してください。"

_GENERATE_PROMPT = """以下のコンテキストから、シグマリスが今日調査すべき問いを2〜3件生成してください。

## ユーザー事実サマリー
{facts_summary}

## 直近の未解決経験
{unresolved}

## 古くなった可能性がある事実
{stale_facts}

---
以下のJSONを出力してください:
{{
  "queries": [
    {{"query": "調査する問い", "reason": "なぜ今調査するか", "source": "stale_fact|unresolved_experience|trend|self_model_gap", "priority": 0.8}},
    ...
  ]
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


async def enqueue_curiosity(
    *,
    query: str,
    reason: str | None = None,
    source: str | None = None,
    priority: float = 0.5,
) -> str | None:
    """Add a query to the curiosity queue. Returns row ID or None."""
    try:
        if source and source not in _VALID_SOURCES:
            logger.warning("curiosity_engine: invalid source=%s", source)
            source = None

        payload: dict[str, Any] = {
            "query": query,
            "priority": max(0.0, min(1.0, priority)),
        }
        if reason:
            payload["reason"] = reason
        if source:
            payload["source"] = source

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
            logger.info("curiosity_engine: enqueued query='%s' id=%s priority=%.2f", query[:60], rid, priority)
            return rid
        return None
    except Exception:
        logger.exception("curiosity_engine: failed to enqueue query='%s'", query[:60])
        return None


async def get_pending_queue(limit: int = 10) -> list[dict[str, Any]]:
    """Return pending items sorted by priority descending."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={
                "status": "eq.pending",
                "order": "priority.desc,created_at.asc",
                "limit": str(limit),
            },
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("curiosity_engine: failed to get_pending_queue")
        return []


async def _mark_status(row_id: str, status: str) -> None:
    try:
        from datetime import datetime, timezone  # noqa: PLC0415
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        payload: dict[str, Any] = {"status": status}
        if status in {"done", "skipped"}:
            payload["executed_at"] = datetime.now(timezone.utc).isoformat()
        r = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"id": f"eq.{row_id}"},
            json=payload,
        )
        r.raise_for_status()
    except Exception:
        logger.exception("curiosity_engine: failed to mark_status id=%s status=%s", row_id, status)


async def execute_curiosity_search() -> dict[str, Any]:
    """
    Daily 6:15 AM scheduled task.
    For each pending query, runs a research search and marks as done.
    Uses research_agent.run_research_for_query if available; else marks skipped.
    """
    results: dict[str, Any] = {"processed": 0, "skipped": 0, "errors": 0}
    try:
        queue = await get_pending_queue(limit=5)
        if not queue:
            logger.info("curiosity_engine: no pending queries")
            return results

        for item in queue:
            row_id = item.get("id", "")
            query = item.get("query", "")
            try:
                await _mark_status(row_id, "searching")
                try:
                    from app.services.research_agent import run_research_for_query  # noqa: PLC0415
                    await run_research_for_query(query)
                    await _mark_status(row_id, "done")
                    results["processed"] = results["processed"] + 1
                except ImportError:
                    await _mark_status(row_id, "skipped")
                    results["skipped"] = results["skipped"] + 1
            except Exception:
                logger.exception("curiosity_engine: error processing query='%s'", query[:60])
                results["errors"] = results["errors"] + 1
                await _mark_status(row_id, "skipped")

        logger.info("curiosity_engine: execute done %s", results)
        return results
    except Exception:
        logger.exception("curiosity_engine: execute_curiosity_search failed")
        return results


async def generate_curiosity_queries(
    *,
    facts_summary: str = "",
    unresolved: str = "",
    stale_facts: str = "",
) -> list[dict[str, Any]]:
    """Use LLM to generate curiosity queries from context. Returns list of query dicts."""
    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": _GENERATE_SYSTEM},
                {"role": "user", "content": _GENERATE_PROMPT.format(
                    facts_summary=facts_summary or "情報なし",
                    unresolved=unresolved or "なし",
                    stale_facts=stale_facts or "なし",
                )},
            ],
            temperature=0.4,
            max_tokens=512,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        queries = parsed.get("queries", []) if isinstance(parsed, dict) else []
        for q in queries:
            await enqueue_curiosity(
                query=q.get("query", ""),
                reason=q.get("reason"),
                source=q.get("source"),
                priority=float(q.get("priority", 0.5)),
            )
        logger.info("curiosity_engine: generated %d queries", len(queries))
        return queries if isinstance(queries, list) else []
    except Exception:
        logger.exception("curiosity_engine: failed to generate_curiosity_queries")
        return []
