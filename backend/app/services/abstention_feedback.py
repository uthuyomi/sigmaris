from __future__ import annotations

# Phase B15: personalized abstention threshold.
#
# B11's category-based thresholds (0.78/0.85/0.5) are fixed and the same
# for everyone. Whether "hedge more" or "hedge less" is the right default
# is a matter of personal preference ("間違うくらいなら黙ってほしい" vs
# "多少不確かでも仮説として出してほしい"), so this phase learns a single
# bounded per-person offset from how 海星さん actually reacts to hedged
# answers, and applies it uniformly to every B11 threshold.
#
# Signal source (same constraint B13 worked under: no explicit feedback UI
# exists) is the very next user reply after a hedged (B11 low_confidence/
# no_evidence) answer, classified fire-and-forget — same shape as A3's
# decision detection / B2's episode detection / B3's confirmation
# reflection, called from orchestrator's _cognitive_layer_bg alongside
# those, so this adds no response-path latency at all (requirement 4).
#
# Pending-hedge tracking mirrors active_inquiry.py's _pending_confirmations
# (Phase B3) exactly: in-process, keyed by thread_id, one-shot (a second
# hedge before the first is reflected simply replaces it — matching a
# reply many turns later back to a stale hedge risks misattributing an
# unrelated reply).

import json
import logging
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_confidence import _MAX_THRESHOLD_ADJUSTMENT
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_abstention_feedback"

_pending_hedges: set[str] = set()

# Noisier signal than B13/B14's evidence (an LLM's read of one short,
# ambiguity-prone conversational reply, not a structured decision record),
# and it directly modulates a safety-oriented behavior (how readily
# Sigmaris hedges), not just search ranking — so the bar is set above
# B13's/B14's minimum of 2, while still reachable within a single-user
# system's realistic interaction volume.
_MIN_EVIDENCE_FOR_ADJUSTMENT = 5

_CLASSIFY_SYSTEM = (
    "あなたはシグマリスの応答傾向学習システムです。シグマリスが確信度の低い"
    "(ヘッジした)回答をした直後の、海星さんの返答を分類します。必ず有効な"
    "JSONのみを返してください。"
)

_CLASSIFY_PROMPT = """シグマリスは直前の応答で、確信度が低いことをヘッジして
伝えました(「もしかしたら〜かもしれません」等)。

海星さんの直後の返答:
{user_reply}

---
この返答を、以下のいずれかに分類してください:

- "push_for_answer": ヘッジを不要と感じ、断定的な回答や推測を求めている
  (例:「もっと詳しく」「じゃあ推測でいいから」「仮でいいから教えて」)
- "supports_caution": ヘッジを適切と感じている、または慎重な姿勢を支持して
  いる(例:「そうだね、確認してから教えて」「無理に答えなくていいよ」)
- "unclear": どちらとも判断できない、または話題が変わった

以下のJSON形式で返してください:
{{"reaction": "push_for_answer" または "supports_caution" または "unclear"}}"""


def record_pending_hedge(thread_id: str | None) -> None:
    """Called from orchestrator's _build_memory_context right after B11
    decides a response will be hedged (tier != "confident")."""
    if thread_id:
        _pending_hedges.add(thread_id)


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


def _latest_user_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


async def record_reaction(
    reaction: str, *, thread_id: str | None, invocation_id: str | None
) -> None:
    """Insert one classified-reaction row into sigmaris_abstention_feedback.

    Public (Phase S-3, docs/sigmaris/phase_s_report.md): dissent.py reuses
    this writer as-is to record dissent_accepted/dissent_pushed_back
    reactions into the same table, rather than duplicating this insert
    logic or creating a parallel table — see the
    202607220049_dissent_feedback.sql migration's comment for why the
    table itself is shared across both B15 (hedging) and S-3 (dissent).
    """
    payload: dict[str, Any] = {"reaction": reaction}
    if thread_id is not None:
        payload["thread_id"] = thread_id
    if invocation_id is not None:
        payload["invocation_id"] = invocation_id

    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.post(
        f"{base_url}/rest/v1/{_TABLE}",
        headers=_svc_headers(prefer="return=minimal"),
        json=payload,
    )
    r.raise_for_status()


async def reflect_abstention_reaction(
    *,
    thread_id: str | None,
    turn_messages: list[dict[str, str]],
    invocation_id: str | None = None,
) -> None:
    """Fire-and-forget: if this thread just received a hedged answer,
    classify the user's very next reply and record it if it's a usable
    signal. No-op (and no LLM call) if there's no pending hedge for this
    thread — the common case on most turns."""
    if not thread_id or thread_id not in _pending_hedges:
        return
    _pending_hedges.discard(thread_id)  # one-shot regardless of outcome below

    user_reply = _latest_user_text(turn_messages)
    if not user_reply:
        return

    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.ABSTENTION_REACTION_DETECTION,
            [
                {"role": "system", "content": _CLASSIFY_SYSTEM},
                {"role": "user", "content": _CLASSIFY_PROMPT.format(user_reply=user_reply[:500])},
            ],
            temperature=0.1,
            max_tokens=100,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return

        reaction = parsed.get("reaction")
        if reaction not in ("push_for_answer", "supports_caution"):
            # "unclear" (or any malformed value) is explicitly never
            # treated as evidence in either direction — per the task's
            # instruction, an ambiguous reply must not skew the count.
            return

        await record_reaction(reaction, thread_id=thread_id, invocation_id=invocation_id)
    except Exception:
        logger.exception(
            "abstention_feedback: failed to reflect_abstention_reaction thread_id=%s", thread_id
        )


async def get_threshold_adjustment() -> float:
    """Aggregate all recorded reactions into a single bounded offset
    (within +/-_MAX_THRESHOLD_ADJUSTMENT) to apply uniformly to every B11
    threshold (see memory_confidence.classify_confidence_tier's
    threshold_adjustment param). Below _MIN_EVIDENCE_FOR_ADJUSTMENT total
    classified reactions, returns 0.0 (no personalization yet) — the same
    "never conclude from sparse evidence" principle B13/B14 established.
    """
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"select": "reaction"},
        )
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list):
            return 0.0

        push_count = sum(1 for row in rows if row.get("reaction") == "push_for_answer")
        caution_count = sum(1 for row in rows if row.get("reaction") == "supports_caution")
        total = push_count + caution_count
        if total < _MIN_EVIDENCE_FOR_ADJUSTMENT:
            return 0.0

        # push dominant (net_ratio > 0) -> lower thresholds (more
        # assertive); caution dominant (net_ratio < 0) -> raise thresholds
        # (more cautious). net_ratio is in [-1, 1], so the result is always
        # within +/-_MAX_THRESHOLD_ADJUSTMENT without needing a separate
        # clamp here (classify_confidence_tier clamps again regardless, as
        # a second layer of protection).
        net_ratio = (push_count - caution_count) / total
        return -net_ratio * _MAX_THRESHOLD_ADJUSTMENT
    except Exception:
        logger.exception("abstention_feedback: failed to get_threshold_adjustment")
        return 0.0
