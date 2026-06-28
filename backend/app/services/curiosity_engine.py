from __future__ import annotations

import json
import logging
import random
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_curiosity_queue"

_VALID_SOURCES = frozenset({"stale_fact", "unresolved_experience", "trend", "self_model_gap"})

# ─── Fallback interests (Article 8) — used when constitution DB not available ──
_INTERESTS_FALLBACK: list[dict[str, str]] = [
    {"value": "意識・クオリア・自己認識の最新研究",           "description": "sub_layer:self"},
    {"value": "認知アーキテクチャの設計パターン",             "description": "sub_layer:self"},
    {"value": "自律エージェントの倫理と設計",                 "description": "sub_layer:self"},
    {"value": "個人事業主・インディーハッカーの知見",         "description": "sub_layer:user"},
    {"value": "SaaS収益化の最新事例",                         "description": "sub_layer:user"},
    {"value": "個人開発者の生産性向上",                       "description": "sub_layer:user"},
    {"value": "ロボティクス・自律システム",                   "description": "sub_layer:tech"},
    {"value": "ローカルLLMの最新動向",                        "description": "sub_layer:tech"},
    {"value": "家庭支援AIの研究",                             "description": "sub_layer:tech"},
]

_GENERATE_SYSTEM = (
    "あなたはシグマリスの好奇心エンジンです。"
    "ユーザーの状況から探索すべき問いを日本語で生成してください。"
    "必ず有効なJSONのみを返してください。"
)

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

_INTEREST_SYSTEM = (
    "あなたはシグマリスの好奇心エンジンです。"
    "シグマリス自身の関心軸とユーザーの目標・情報を組み合わせて、"
    "今週調査すべき具体的な検索クエリを生成してください。"
    "必ず有効なJSONのみを返してください。"
)

_INTEREST_PROMPT = """シグマリスの関心軸とユーザー情報を組み合わせて、今週調査すべきクエリを1〜2件生成してください。

## シグマリスの関心軸（今回の対象）
{interests}

## ユーザーの目標・事実
{user_context}

---
具体化の例:
- 「SaaS収益化」+「ユーザーがAdFlow AIを開発中」→「個人開発SaaS 初期収益化 事例 2026」
- 「ローカルLLMの最新動向」+「シグマリスの自己改善目標」→「Ollama Llama3 2026 最新モデル 自己ホスト」

以下のJSONを出力してください:
{{
  "queries": [
    {{"query": "具体的な検索クエリ（日本語+英語混在可・40文字以内）", "reason": "なぜ今このクエリか（関心軸とユーザー情報の接点）", "priority": 0.6}}
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


async def _load_interests() -> list[dict[str, Any]]:
    """Load Article 8 interests from constitution DB; fall back to hardcoded list."""
    try:
        from app.services.constitution import get_interests  # noqa: PLC0415
        rows = await get_interests()
        if rows:
            return rows
    except Exception:
        logger.warning("curiosity_engine: could not load interests from constitution, using fallback")
    return list(_INTERESTS_FALLBACK)


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
    """Use LLM to generate curiosity queries from user context. Returns list of query dicts."""
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


async def generate_self_interest_queries(*, user_context: str = "") -> list[dict[str, Any]]:
    """
    Sunday 5:30 AM scheduled task (Article 8).
    Reads Sigmaris's own interest axes from constitution (layer='interest'),
    picks 1-2 at random, combines with user context, and generates concrete
    search queries via LLM.
    Returns list of enqueued query dicts.
    """
    try:
        all_interests = await _load_interests()
        if not all_interests:
            logger.warning("curiosity_engine: no interests found, skipping self-interest generation")
            return []

        # Pick 1-2 random interests across sub-layers for variety
        count = min(2, len(all_interests))
        chosen = random.sample(all_interests, count)
        interest_lines = "\n".join(
            f"- [{r.get('description', '').replace('sub_layer:', '')}] {r.get('value', '')}"
            for r in chosen
        )

        if not user_context:
            try:
                from app.services.proactive.jwt_manager import get_sigmaris_jwt  # noqa: PLC0415
                from app.services.user_fact_data import build_profile_context, get_user_profile  # noqa: PLC0415
                jwt = await get_sigmaris_jwt()
                profile = await get_user_profile(jwt)
                user_context = build_profile_context(profile) or "情報なし"
            except Exception:
                user_context = "情報なし"

        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": _INTEREST_SYSTEM},
                {"role": "user", "content": _INTEREST_PROMPT.format(
                    interests=interest_lines,
                    user_context=user_context[:600],
                )},
            ],
            temperature=0.5,
            max_tokens=512,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        queries = parsed.get("queries", []) if isinstance(parsed, dict) else []

        enqueued: list[dict[str, Any]] = []
        for q in queries:
            query_text = (q.get("query") or "").strip()
            if not query_text:
                continue
            rid = await enqueue_curiosity(
                query=query_text,
                reason=q.get("reason"),
                source="self_model_gap",
                priority=float(q.get("priority", 0.6)),
            )
            if rid:
                enqueued.append({**q, "id": rid})

        logger.info(
            "curiosity_engine: self-interest queries generated=%d interests_used=%s",
            len(enqueued),
            [r.get("value", "")[:30] for r in chosen],
        )
        return enqueued
    except Exception:
        logger.exception("curiosity_engine: failed to generate_self_interest_queries")
        return []
