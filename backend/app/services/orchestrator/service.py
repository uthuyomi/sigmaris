from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from app.config import settings
from app.services.orchestrator.agent_registry import get_schedule_agent
from app.services.orchestrator.audit import finish_invocation, start_invocation
from app.services.orchestrator.persona_loader import load_persona
from app.services.orchestrator.persona_rewriter import rewrite_with_persona
from app.services.orchestrator.response_guard import replace_forbidden_assistant_names
from app.services.orchestrator.schedule_agent_client import call_schedule_agent
from app.services.supabase_rest import get_current_user
from app.services.self_model import get_self_model
from app.services.user_fact_data import (
    build_facts_context,
    build_profile_context,
    extract_call_name,
    get_fact_items,
    get_user_profile,
)

logger = logging.getLogger(__name__)

# ─── 5-minute TTL cache for expensive pre-response DB reads ──────────────────
_CACHE_TTL = 300.0  # seconds

_cache: dict[str, tuple[float, Any]] = {}  # key → (timestamp, value)


def _cache_get(key: str) -> tuple[bool, Any]:
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0] < _CACHE_TTL):
        return True, entry[1]
    return False, None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


async def _timed(coro, *, timeout: float = 5.0, default: Any = None) -> Any:
    """Await coro with a hard timeout; return default on timeout or error."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("orchestrator: timed out (%.1fs)", timeout)
        return default
    except Exception:
        return default


async def _cached_self_model() -> dict | None:
    hit, val = _cache_get("self_model")
    if hit:
        return val
    result = await _timed(get_self_model(), timeout=5.0)
    _cache_set("self_model", result)
    return result


async def _cached_user_profile(jwt: str) -> dict | None:
    key = f"profile:{jwt[:20]}"
    hit, val = _cache_get(key)
    if hit:
        return val
    result = await _timed(get_user_profile(jwt), timeout=5.0)
    _cache_set(key, result)
    return result


async def _cached_fact_items(jwt: str) -> list | None:
    key = f"facts:{jwt[:20]}"
    hit, val = _cache_get(key)
    if hit:
        return val
    result = await _timed(get_fact_items(jwt, active_only=True), timeout=5.0)
    _cache_set(key, result)
    return result


async def _cached_active_trends(jwt: str) -> list:
    key = f"trends:{jwt[:20]}"
    hit, val = _cache_get(key)
    if hit:
        return val
    try:
        from app.services.trend_analyzer import get_active_trends  # noqa: PLC0415
        result = await _timed(get_active_trends(jwt), timeout=5.0, default=[])
    except Exception:
        result = []
    _cache_set(key, result)
    return result or []


# ─── Context builders ─────────────────────────────────────────────────────────


def _build_self_model_context(model: dict | None) -> str | None:
    if not model:
        return None
    identity = (model.get("identity_statement") or "").strip()
    if not identity:
        return None
    # Trim identity to 150 chars to keep context light
    identity_short = identity[:150] + ("…" if len(identity) > 150 else "")
    goals = model.get("current_goals") or []
    lines = [f"[シグマリス自己認識]\n{identity_short}"]
    if goals:
        goal_str = "・".join(str(g) for g in goals[:3])  # max 3 goals
        lines.append(f"目標: {goal_str}")
    return "\n".join(lines)


def _build_trends_context(trends: list) -> str | None:
    if not trends:
        return None
    top = trends[:3]  # top 3 only
    lines = ["[傾向トピック]"]
    for t in top:
        label = (t.get("topic_label") or t.get("topic") or "").strip()
        if label:
            lines.append(f"・{label}")
    return "\n".join(lines) if len(lines) > 1 else None


def _user_display_name(user: dict[str, Any]) -> str | None:
    metadata = user.get("user_metadata")
    if not isinstance(metadata, dict):
        return None
    for key in ("full_name", "name", "display_name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ─── Background tasks ─────────────────────────────────────────────────────────


async def _cognitive_layer_bg(*, invocation_id: str) -> None:
    """Fire-and-forget: log decision and nudge internal state after each chat turn."""
    try:
        from app.services.decision_log import log_decision  # noqa: PLC0415
        from app.services.internal_state import get_internal_state, snapshot, update_internal_state  # noqa: PLC0415
        state_snap = await snapshot()
        await log_decision(
            decision_type="action",
            title=f"chat_turn:{invocation_id[:8]}",
            reason="Orchestrator processed a user conversation turn.",
            internal_state_snapshot=state_snap,
        )
        state = await get_internal_state()
        await update_internal_state(
            curiosity=min(1.0, float(state.get("curiosity", 0.5)) + 0.01),
            stability=min(1.0, float(state.get("stability", 0.8)) + 0.005),
        )
    except Exception:
        logger.exception("cognitive_layer_bg: failed for invocation=%s", invocation_id)


# ─── Main entry point ─────────────────────────────────────────────────────────


async def run_orchestrator_chat(
    *,
    jwt: str,
    google_access_token: str | None,
    google_refresh_token: str | None,
    messages: list[dict[str, str]],
    thread_id: str | None,
    request_context: dict[str, Any] | None,
) -> dict[str, Any]:
    started_at = time.monotonic()
    invocation_id = str(uuid.uuid4())

    # Auth check (no cache — must be fresh every request)
    user = await _timed(get_current_user(jwt), timeout=5.0)
    if not user:
        raise RuntimeError("Failed to authenticate user (timeout or error).")
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise RuntimeError("Authenticated Supabase user did not include an id.")

    persona = load_persona()
    agent = get_schedule_agent()

    # Parallel-load context with cache + 5s timeout each
    fact_profile, fact_items, self_model, active_trends = await asyncio.gather(
        _cached_user_profile(jwt),
        _cached_fact_items(jwt),
        _cached_self_model(),
        _cached_active_trends(jwt),
        return_exceptions=False,
    )

    reason = "User requested schedule assistance through the Sigmaris orchestrator."
    caller_agent_id = settings.schedule_agent_id
    if request_context and isinstance(request_context, dict):
        if isinstance(request_context.get("reason"), str):
            supplied_reason = request_context["reason"].strip()
            if supplied_reason:
                reason = supplied_reason[:500]
        if isinstance(request_context.get("caller_agent_id"), str):
            caller_agent_id = request_context["caller_agent_id"][:80]

    audit_row = await start_invocation(
        jwt=jwt,
        invocation_id=invocation_id,
        user_id=user_id,
        caller_agent_id=caller_agent_id,
        target_agent_id=agent.agent_id,
        target_endpoint=agent.chat_endpoint,
        reason=reason,
        request_summary={
            "messageCount": len(messages),
            "latestRole": messages[-1]["role"],
            "hasGoogleAccessToken": bool(google_access_token),
            "hasGoogleRefreshToken": bool(google_refresh_token),
        },
        persona_version=persona.version,
        persona_hash=persona.sha256,
    )
    audit_row_id = str(audit_row["id"])

    # Build lightweight context (profile 200 chars, facts top 5, trends top 3)
    profile_context = build_profile_context(fact_profile)
    if profile_context and len(profile_context) > 200:
        profile_context = profile_context[:200] + "…"

    facts_ctx = build_facts_context(fact_items or [], top_n=5)
    if facts_ctx and profile_context:
        profile_context = profile_context + "\n\n" + facts_ctx
    elif facts_ctx:
        profile_context = facts_ctx

    trends_ctx = _build_trends_context(active_trends)
    if trends_ctx and profile_context:
        profile_context = profile_context + "\n\n" + trends_ctx
    elif trends_ctx:
        profile_context = trends_ctx

    call_name = extract_call_name(fact_profile) or _user_display_name(user)
    self_model_context = _build_self_model_context(self_model)

    try:
        schedule_result = await call_schedule_agent(
            agent=agent,
            jwt=jwt,
            google_access_token=google_access_token,
            google_refresh_token=google_refresh_token,
            messages=messages,
            thread_id=thread_id,
            invocation_id=invocation_id,
            reason=f"orchestrator:{invocation_id}:{reason}",
            user_profile_context=profile_context,
            self_model_context=self_model_context,
        )
        rewrite = await rewrite_with_persona(
            source=schedule_result.text,
            persona=persona,
            user_name=call_name,
        )
        response_text = replace_forbidden_assistant_names(rewrite.text)
    except Exception as error:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        try:
            await finish_invocation(
                jwt=jwt,
                audit_row_id=audit_row_id,
                status="failed",
                response_summary=None,
                error_code=type(error).__name__,
                duration_ms=duration_ms,
            )
        except Exception as audit_error:
            raise RuntimeError(
                f"Invocation failed and its mandatory audit update also failed: {audit_error}"
            ) from audit_error
        raise

    duration_ms = int((time.monotonic() - started_at) * 1000)
    await finish_invocation(
        jwt=jwt,
        audit_row_id=audit_row_id,
        status="completed_with_fallback" if rewrite.used_fallback else "completed",
        response_summary={
            "scheduleMessageId": schedule_result.message_id,
            "usedFallback": rewrite.used_fallback,
            "guardViolations": list(rewrite.guard_violations),
            "responseLength": len(response_text),
        },
        error_code=None,
        duration_ms=duration_ms,
    )

    # Append active inquiry question if available (max one per turn)
    try:
        from app.services.active_inquiry import get_inquiry_question  # noqa: PLC0415
        full_messages_so_far = list(messages) + [{"role": "assistant", "content": response_text}]
        inquiry = await asyncio.wait_for(
            get_inquiry_question(jwt, full_messages_so_far), timeout=3.0
        )
        if inquiry:
            response_text = response_text + "\n\n" + inquiry
    except (asyncio.TimeoutError, Exception):
        pass  # Never block the response for inquiry failures

    # Fire-and-forget: extract memorable facts from this conversation turn.
    from app.services.memory_extractor import extract_from_conversation  # noqa: PLC0415
    full_messages = list(messages) + [{"role": "assistant", "content": response_text}]
    asyncio.create_task(
        extract_from_conversation(messages=full_messages, jwt=jwt),
        name=f"memory_extract:{invocation_id}",
    )

    # Fire-and-forget: cognitive layer (decision log + internal state update).
    asyncio.create_task(
        _cognitive_layer_bg(invocation_id=invocation_id),
        name=f"cognitive_layer:{invocation_id}",
    )

    # Invalidate context cache after response so next turn picks up any new facts
    # (only invalidate facts — profile and self_model change less frequently)
    _cache.pop(f"facts:{jwt[:20]}", None)

    return {
        "ok": True,
        "text": response_text,
        "thread_id": schedule_result.thread_id,
        "invocation_id": invocation_id,
        "agent_id": agent.agent_id,
        "used_fallback": rewrite.used_fallback,
    }
