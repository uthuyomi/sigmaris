from __future__ import annotations

# Phase B6: topic transition tracking.
#
# Role vs. the other memory layers this conversation flow already touches
# (see phase_b6_report.md section 2 for the full writeup):
#
# - Phase A1's cross-thread recent-log window (orchestrator/service.py's
#   _prepare_session_messages): the raw conversation itself — what was
#   actually said, verbatim.
# - Phase B2's sigmaris_experience: durable "what happened" records — an
#   event worth remembering on its own, independent of which conversation
#   surfaces it later.
# - sigmaris_topic_log (this module): neither of those. Just a lightweight,
#   running table-of-contents answering "what is being talked about right
#   now" — a handful of words, nothing more. It does not store what was
#   said or what happened, only a label and when the label changed. This
#   is intentionally *not* a topic taxonomy or a graph of related topics —
#   just a flat, timestamped sequence of short strings.

import json
import logging
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_topic_log"

_DETECT_SYSTEM = (
    "あなたはシグマリスの話題追跡システムです。会話の話題が変わったかどうかを判"
    "定します。話題は厳密に分類せず、数語程度の短いラベルで表現してください。雑"
    "談の範囲内の些細な変化では「変わった」と判定しないでください。必ず有効な"
    "JSONのみを返してください。"
)

_DETECT_PROMPT = """現在の話題ラベル: {current_topic}

直近のやり取り:
{transcript}

---
このやり取りの話題が、現在の話題ラベルから明確に変わった場合のみ、以下のJSON
を出力してください:
{{
  "changed": true,
  "new_topic_label": "新しい話題を表す数語程度の短いラベル"
}}

話題が変わっていない場合(同じ話題の続き、雑談の範囲内の変化、現在の話題ラベル
がまだ無い状態で話題と呼べるほどの内容がない場合を含む)は以下のみ返してくださ
い:
{{"changed": false}}"""

_NO_CURRENT_TOPIC_LABEL = "(なし — まだ話題が記録されていません)"


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


def _format_transcript(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = "海星" if message.get("role") == "user" else "シグマリス"
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def get_recent_topics(limit: int = 2) -> list[dict[str, Any]]:
    """Return the most recent topic_log rows, newest first.

    limit=2 is what get_current_and_previous_topic() needs (current +
    previous); a larger limit is only useful for detect_and_record_topic_
    transition()'s "what's the current label" lookup, which only needs 1
    but reuses this same helper for simplicity.
    """
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"order": "created_at.desc", "limit": str(limit)},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("topic_tracker: failed to get_recent_topics")
        return []


async def get_current_and_previous_topic() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (current_topic_row, previous_topic_row); either may be None."""
    rows = await get_recent_topics(limit=2)
    current = rows[0] if len(rows) > 0 else None
    previous = rows[1] if len(rows) > 1 else None
    return current, previous


async def get_topics_by_ids(topic_ids: list[str]) -> list[dict[str, Any]]:
    """Return sigmaris_topic_log rows for a specific set of ids.

    Phase R-1 (docs/sigmaris/phase_r_report.md): the dereferencing step
    cycle_trace.py uses to turn sigmaris_goal_alignment_flags.evidence_refs
    (a mixed decision_log/topic_log id set) into the actual topic rows
    among that evidence.
    """
    ids = [str(tid) for tid in topic_ids if tid]
    if not ids:
        return []
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"id": f"in.({','.join(ids)})"},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("topic_tracker: failed to get_topics_by_ids")
        return []


async def _record_topic(
    *,
    topic_label: str,
    thread_id: str | None,
    invocation_id: str | None,
) -> str | None:
    try:
        payload: dict[str, Any] = {"topic_label": topic_label}
        if thread_id is not None:
            payload["thread_id"] = thread_id
        if invocation_id is not None:
            payload["invocation_id"] = invocation_id

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
            logger.info("topic_tracker: recorded new topic '%s' id=%s", topic_label, rid)
            return rid
        return None
    except Exception:
        logger.exception("topic_tracker: failed to record topic '%s'", topic_label)
        return None


async def detect_and_record_topic_transition(
    *,
    messages: list[dict[str, str]],
    thread_id: str | None = None,
    invocation_id: str | None = None,
) -> str | None:
    """Fire-and-forget: ask the LLM whether the just-completed turn's topic
    differs from the currently-recorded one; if so, append a new row.
    Mirrors decision_log.detect_and_record_decision() /
    experience_layer.detect_and_record_episode()'s shape — same
    fire-and-forget entry point (orchestrator's _cognitive_layer_bg), same
    per-turn-scoped transcript, same has_x/false-by-default contract.

    Deliberately does *not* create a new row when the topic hasn't changed
    (requirement 2) — this function is a no-op in the common case where a
    conversation continues on the same subject across many turns.
    """
    try:
        transcript = _format_transcript(messages)
        if not transcript:
            return None

        current_rows = await get_recent_topics(limit=1)
        current_label = current_rows[0].get("topic_label") if current_rows else None
        current_label_display = current_label if isinstance(current_label, str) and current_label.strip() else _NO_CURRENT_TOPIC_LABEL

        router = get_llm_router()
        raw = await router.chat(
            TaskType.TOPIC_DETECTION,
            [
                {"role": "system", "content": _DETECT_SYSTEM},
                {"role": "user", "content": _DETECT_PROMPT.format(
                    current_topic=current_label_display,
                    transcript=transcript,
                )},
            ],
            temperature=0.1,
            max_tokens=200,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict) or not parsed.get("changed"):
            return None

        new_label = str(parsed.get("new_topic_label") or "").strip()
        if not new_label:
            return None
        # Defensive de-dup: an LLM claiming "changed" with a label
        # identical (case/whitespace-insensitive) to the current one would
        # otherwise still create a redundant row.
        if isinstance(current_label, str) and new_label.strip().lower() == current_label.strip().lower():
            return None

        return await _record_topic(
            topic_label=new_label[:200],
            thread_id=thread_id,
            invocation_id=invocation_id,
        )
    except Exception:
        logger.exception("topic_tracker: failed to detect_and_record_topic_transition")
        return None
