from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.supabase_rest import _get_client, _require_supabase_config
from app.services.user_fact_data import build_facts_context

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_decision_log"

_VALID_TYPES = frozenset({"proposal", "refusal", "notification", "action", "policy_change"})

_DETECT_SYSTEM = (
    "あなたはシグマリスの意思決定検出システムです。会話のやり取りに、決定・"
    "方針転換・重要な選択が含まれるかを判定します。雑談・確認・単純な質問"
    "応答・情報の読み上げには反応しないでください。必ず有効なJSONのみを返"
    "してください。"
)

_DETECT_PROMPT = """以下の直近のやり取りを確認してください。

## 直近のやり取り
{transcript}

## 海星さんの既知の事実（参考。関連があれば related_fact_keys に category/key の形式で引用してよい）
{facts_context}

## 現在アクティブな直近の決定事項（{active_count}件。今回の内容がこれらのいずれかを置き換える場合はそのidを返す）
{active_decisions}

---
このやり取りに、決定・方針転換・重要な選択（例:「AではなくBにする」「〜す
ることにした」「今後は〜する」）が明確に含まれる場合のみ、以下のJSONを出力
してください:
{{
  "has_decision": true,
  "decision_type": "policy_change または proposal",
  "title": "決定内容の要約（40文字以内）",
  "reason": "なぜその決定に至ったか（会話内容から）",
  "outcome": "決定の具体的内容",
  "related_fact_keys": ["category/key", "..."],
  "supersedes_decision_id": "置き換える決定のid、なければnull"
}}

含まれない場合（雑談・単純な質問・確認のみ・情報照会のみ等）は以下のみ返し
てください:
{{"has_decision": false}}"""

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
    thread_id: str | None = None,
    invocation_id: str | None = None,
    supersedes: str | None = None,
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
        if thread_id is not None:
            payload["thread_id"] = thread_id
        if invocation_id is not None:
            payload["invocation_id"] = invocation_id
        if supersedes is not None:
            payload["supersedes"] = supersedes

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


async def mark_superseded(old_decision_id: str, new_decision_id: str) -> bool:
    """Point an old decision's superseded_by at the new decision that replaced
    it. The old row is never deleted or overwritten — this just links it
    forward so the supersede chain can be followed in either direction."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            params={"id": f"eq.{old_decision_id}"},
            json={"superseded_by": new_decision_id},
        )
        r.raise_for_status()
        logger.info("decision_log: id=%s superseded_by=%s", old_decision_id, new_decision_id)
        return True
    except Exception:
        logger.exception("decision_log: failed to mark_superseded id=%s", old_decision_id)
        return False


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


def _format_transcript(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = "海星" if message.get("role") == "user" else "シグマリス"
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def detect_and_record_decision(
    *,
    messages: list[dict[str, str]],
    fact_items: list[dict[str, Any]] | None = None,
    thread_id: str | None = None,
    invocation_id: str | None = None,
) -> str | None:
    """Fire-and-forget: ask the LLM whether the just-completed turn contains
    an actual decision or policy change (not small talk / a plain question).
    If so, record it — and if it replaces an earlier active decision, link
    the old row forward via mark_superseded() instead of touching it.

    `messages` should be just the current turn (the latest user message plus
    the assistant's reply) — not the full cross-thread session window —
    so the same earlier exchange isn't re-detected as "a new decision" on
    every subsequent turn it happens to still be in context for.
    """
    try:
        transcript = _format_transcript(messages)
        if not transcript:
            return None

        facts_context = build_facts_context(fact_items or [], top_n=15) or "（なし）"

        active_decisions = [
            d for d in await get_recent_decisions(limit=10) if not d.get("superseded_by")
        ]
        active_lines = "\n".join(
            f"- id={d.get('id')} type={d.get('decision_type')} "
            f"title={d.get('title')} outcome={d.get('outcome') or 'N/A'}"
            for d in active_decisions
        ) or "（なし）"

        router = get_llm_router()
        raw = await router.chat(
            TaskType.DECISION_DETECTION,
            [
                {"role": "system", "content": _DETECT_SYSTEM},
                {"role": "user", "content": _DETECT_PROMPT.format(
                    transcript=transcript,
                    facts_context=facts_context,
                    active_count=len(active_decisions),
                    active_decisions=active_lines,
                )},
            ],
            temperature=0.1,
            max_tokens=400,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict) or not parsed.get("has_decision"):
            return None

        decision_type = parsed.get("decision_type")
        if decision_type not in _VALID_TYPES:
            decision_type = "policy_change"

        title = str(parsed.get("title") or "").strip()[:200] or transcript[:80]

        fact_lookup = {
            f"{item.get('category')}/{item.get('key')}": item.get("id")
            for item in (fact_items or [])
            if item.get("id")
        }
        related_keys = parsed.get("related_fact_keys")
        memory_refs = [
            fact_lookup[key]
            for key in (related_keys if isinstance(related_keys, list) else [])
            if isinstance(key, str) and key in fact_lookup
        ]

        active_ids = {d.get("id") for d in active_decisions}
        supersedes_id = parsed.get("supersedes_decision_id")
        if not isinstance(supersedes_id, str) or supersedes_id not in active_ids:
            supersedes_id = None

        from app.services.internal_state import snapshot  # noqa: PLC0415
        state_snapshot = await snapshot()

        new_id = await log_decision(
            decision_type=decision_type,
            title=title,
            reason=parsed.get("reason"),
            outcome=parsed.get("outcome"),
            memory_refs=memory_refs,
            internal_state_snapshot=state_snapshot,
            thread_id=thread_id,
            invocation_id=invocation_id,
            supersedes=supersedes_id,
        )
        if new_id and supersedes_id:
            await mark_superseded(supersedes_id, new_id)
        return new_id
    except Exception:
        logger.exception("decision_log: failed to detect_and_record_decision")
        return None
