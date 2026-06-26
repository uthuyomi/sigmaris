from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.local_llm import TaskType, get_llm_router
from app.services.supabase_rest import rest_rpc, rest_select, rest_update

logger = logging.getLogger(__name__)

_SYSTEM = """あなたはユーザーの行動・生活パターンを分析するAIです。
事実記憶と会話履歴から、繰り返し見られる傾向を検出してください。
必ず有効なJSONのみを返してください。"""

_PROMPT = """以下のユーザー記憶と最近の会話ログから、繰り返し見られる傾向を検出してください。

## ユーザー記憶（上位30件）
{facts}

## 最近の会話ログ件数（直近30日）
{log_count}件

対象カテゴリ:
- lifestyle: 生活習慣・睡眠・食事・運動
- health: 健康状態・体調の傾向
- work: 仕事・タスク管理の傾向
- mood: 感情・気分の変化パターン
- behavior: 行動・意思決定パターン

JSON形式で返してください:
{{
  "trends": [
    {{
      "category": "カテゴリ名",
      "trend_key": "snake_case_key",
      "trend_description": "傾向の説明（100文字以内）",
      "evidence": ["根拠1", "根拠2"],
      "confidence": 0.7
    }}
  ]
}}
傾向がなければ trends は空リスト。trend_key は英語のsnake_case。最大10件。"""

# Mark trends not updated within this many days as inactive
_STALE_DAYS = 30


async def analyze_trends(jwt: str) -> dict[str, Any]:
    """
    Detect behavioural trends from fact memory and audit logs.
    Upserts detected trends into user_trend_items.
    Marks trends not updated in 30+ days as is_active=false.
    """
    result: dict[str, Any] = {"upserted": 0, "deactivated": 0, "errors": 0}

    # ── Gather inputs ────────────────────────────────────────────────────────
    try:
        facts = await rest_select(jwt, "user_fact_items", {
            "select": "category,key,value,confidence,importance_score",
            "is_deleted": "eq.false",
            "value": "not.is.null",
            "order": "importance_score.desc,confidence.desc",
            "limit": "30",
        })
        if not isinstance(facts, list):
            facts = []
    except Exception:
        logger.exception("trend_analyzer: failed to fetch facts")
        facts = []

    # Audit log count for the last 30 days
    log_count = 0
    try:
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        logs = await rest_select(jwt, "agent_invocation_audit_logs", {
            "select": "id",
            "created_at": f"gte.{thirty_days_ago}",
            "status": "eq.completed",
        })
        log_count = len(logs) if isinstance(logs, list) else 0
    except Exception:
        logger.warning("trend_analyzer: could not fetch audit logs")

    if not facts:
        logger.info("trend_analyzer: no facts to analyze")
        return result

    # ── LLM trend detection ──────────────────────────────────────────────────
    facts_text = "\n".join(
        f"- [{f.get('category')}] {f.get('key')}: {f.get('value')}"
        for f in facts
    )
    prompt = _PROMPT.format(facts=facts_text, log_count=log_count)

    router = get_llm_router()
    try:
        raw = await router.chat(
            TaskType.COMPLEX_REASONING,
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2048,
            json_mode=True,
        )
        parsed = json.loads(raw)
        trends: list[dict] = parsed.get("trends", [])
    except Exception:
        logger.exception("trend_analyzer: LLM call or JSON parse failed")
        return result

    # ── Upsert detected trends ───────────────────────────────────────────────
    for trend in trends:
        if not _is_valid_trend(trend):
            continue
        try:
            await rest_rpc(jwt, "upsert_trend_item", {
                "p_category":          trend["category"],
                "p_trend_key":         trend["trend_key"],
                "p_trend_description": trend["trend_description"],
                "p_evidence":          json.dumps(trend.get("evidence", []), ensure_ascii=False),
                "p_confidence":        float(trend.get("confidence", 0.5)),
            })
            result["upserted"] += 1
        except Exception:
            logger.exception(
                "trend_analyzer: upsert failed %s/%s",
                trend.get("category"), trend.get("trend_key"),
            )
            result["errors"] += 1

    # ── Deactivate stale trends ──────────────────────────────────────────────
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=_STALE_DAYS)).isoformat()
    try:
        active_trends = await rest_select(jwt, "user_trend_items", {
            "select": "id,last_updated_at",
            "is_active": "eq.true",
        })
        if isinstance(active_trends, list):
            for t in active_trends:
                upd = t.get("last_updated_at") or ""
                if upd < stale_cutoff:
                    try:
                        await rest_update(jwt, "user_trend_items",
                                          {"is_active": False},
                                          {"id": f"eq.{t['id']}"})
                        result["deactivated"] += 1
                    except Exception:
                        logger.exception("trend_analyzer: deactivate failed id=%s", t.get("id"))
                        result["errors"] += 1
    except Exception:
        logger.warning("trend_analyzer: could not check for stale trends")

    logger.info(
        "trend_analyzer: done — upserted=%d deactivated=%d errors=%d",
        result["upserted"], result["deactivated"], result["errors"],
    )
    return result


async def get_active_trends(jwt: str) -> list[dict[str, Any]]:
    """Return all is_active=true trend items for the user."""
    try:
        rows = await rest_select(jwt, "user_trend_items", {
            "select": "category,trend_key,trend_description,evidence,confidence,last_updated_at",
            "is_active": "eq.true",
            "order": "confidence.desc,last_updated_at.desc",
        })
        return rows if isinstance(rows, list) else []
    except Exception:
        logger.exception("trend_analyzer: get_active_trends failed")
        return []


def _is_valid_trend(trend: Any) -> bool:
    if not isinstance(trend, dict):
        return False
    for field in ("category", "trend_key", "trend_description"):
        if not isinstance(trend.get(field), str) or not trend[field].strip():
            return False
    valid_categories = {"lifestyle", "health", "work", "mood", "behavior"}
    if trend["category"] not in valid_categories:
        return False
    conf = trend.get("confidence")
    if conf is not None and not isinstance(conf, (int, float)):
        return False
    return True
