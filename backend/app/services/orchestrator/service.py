from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.app_chat_data import create_chat_thread, get_chat_thread, get_recent_messages_across_threads
from app.services.chat_messages import CONFIRMATION_MARKER_RE
from app.services.orchestrator.agent_registry import get_schedule_agent
from app.services.orchestrator.audit import finish_invocation, start_invocation
from app.services.orchestrator.persona_loader import load_persona
from app.services.orchestrator.persona_rewriter import rewrite_with_persona, rewrite_with_persona_stream
from app.services.orchestrator.response_guard import replace_forbidden_assistant_names
from app.services.orchestrator.schedule_agent_client import call_schedule_agent, call_schedule_agent_stream
from app.services.supabase_rest import get_current_user
from app.services.memory_search import search_relevant_memories
from app.services.self_model import get_self_model
from app.services.user_fact_data import (
    build_facts_context,
    build_profile_context,
    extract_call_name,
    get_fact_items_for_user,
    get_fact_items,
    get_user_profile,
)

logger = logging.getLogger(__name__)

# ─── 5-minute TTL cache for expensive pre-response DB reads ──────────────────
_CACHE_TTL = 300.0  # seconds

_cache: dict[str, tuple[float, Any]] = {}  # key → (timestamp, value)


@dataclass(frozen=True)
class OrchestratorStreamEvent:
    delta: str = ""
    done: bool = False
    thread_id: str | None = None
    invocation_id: str | None = None
    agent_id: str | None = None
    used_fallback: bool = False
    guard_violations: tuple[str, ...] = ()
    tool_event: dict[str, Any] | None = None


def _cache_get(key: str) -> tuple[bool, Any]:
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0] < _CACHE_TTL):
        return True, entry[1]
    return False, None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


async def _timed(coro, *, timeout: float = 5.0, default: Any = None, label: str | None = None) -> Any:
    """Await coro with a hard timeout; return default on timeout or error."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("orchestrator: timed out%s (%.1fs)", f" during {label}" if label else "", timeout)
        return default
    except Exception:
        if label:
            logger.exception("orchestrator: failed during %s", label)
        return default


async def _cached_self_model() -> dict | None:
    hit, val = _cache_get("self_model")
    if hit:
        return val
    result = await _timed(get_self_model(), timeout=3.0, label="self_model")
    _cache_set("self_model", result)
    return result


async def _cached_user_profile(jwt: str) -> dict | None:
    key = f"profile:{jwt[:20]}"
    hit, val = _cache_get(key)
    if hit:
        return val
    result = await _timed(get_user_profile(jwt), timeout=3.0, label="user_profile")
    _cache_set(key, result)
    return result


async def _cached_fact_items(jwt: str, user_id: str) -> list:
    key = f"facts:{user_id}"
    hit, val = _cache_get(key)
    if hit:
        return val

    result = await _timed(get_fact_items(jwt, active_only=True), timeout=3.0, default=[], label="fact_items_rls")
    if not result:
        result = await _timed(
            get_fact_items_for_user(user_id, active_only=True),
            timeout=3.0,
            default=[],
            label="fact_items_service_role",
        )
    logger.info("orchestrator: loaded fact_items count=%d user_id=%s", len(result or []), user_id)
    _cache_set(key, result)
    return result or []


async def _cached_active_trends(jwt: str) -> list:
    key = f"trends:{jwt[:20]}"
    hit, val = _cache_get(key)
    if hit:
        return val
    try:
        from app.services.trend_analyzer import get_active_trends  # noqa: PLC0415
        result = await _timed(get_active_trends(jwt), timeout=2.0, default=[], label="active_trends")
    except Exception:
        result = []
    _cache_set(key, result)
    return result or []


# ─── Context builders ─────────────────────────────────────────────────────────


def _format_self_model_freshness(last_reflected_at: Any) -> str:
    """Day-granularity "how stale is this" label for identity_statement.

    identity_statement is written by a ~daily self-reflection cycle
    (heartbeat.py's 24h cooldown) and, unlike fact-memory/RAG context, was
    being injected into every turn with zero indication of when it was
    written — so the model had no way to tell a months-old self-description
    from something that "just happened". Deliberately rounded to whole days
    (JST calendar-day difference, not hours/minutes): base_system already
    isn't turn-stable for OpenAI's prefix cache because of the fact-memory
    RAG portion (see chat_prompts.py's ordering comment), so this adds no
    *additional* cache churn beyond what already exists — but keeping it at
    day-resolution rather than finer avoids making that pre-existing
    situation any worse.
    """
    if not last_reflected_at:
        return "(最終更新: 不明 — 古い情報の可能性があるため断定的に話さないこと)"
    try:
        reflected_dt = datetime.fromisoformat(str(last_reflected_at).replace("Z", "+00:00"))
    except ValueError:
        return "(最終更新: 不明 — 古い情報の可能性があるため断定的に話さないこと)"

    tz = ZoneInfo("Asia/Tokyo")
    days_elapsed = (datetime.now(tz).date() - reflected_dt.astimezone(tz).date()).days

    if days_elapsed <= 0:
        when = "本日"
    elif days_elapsed == 1:
        when = "1日前"
    else:
        when = f"{days_elapsed}日前"

    note = f"(最終更新: {when}"
    if days_elapsed >= 7:
        note += " — 古い情報である可能性が高いため、現在進行中の出来事であるかのように話さないこと"
    return note + ")"


def _build_self_model_context(model: dict | None) -> str | None:
    if not model:
        return None
    identity = (model.get("identity_statement") or "").strip()
    if not identity:
        return None
    # Trim identity to 150 chars to keep context light
    identity_short = identity[:150] + ("…" if len(identity) > 150 else "")
    freshness_note = _format_self_model_freshness(model.get("last_reflected_at"))
    goals = model.get("current_goals") or []
    lines = [f"[シグマリス自己認識] {freshness_note}\n{identity_short}"]
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


def _latest_user_content(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _build_relevant_memories_context(memories: list[dict[str, Any]]) -> str | None:
    if not memories:
        return None
    lines = ["[関連する事実記憶]"]
    for item in memories:
        category = item.get("category") or ""
        key = item.get("fact_key") or item.get("key") or ""
        value = item.get("value") or ""
        confidence = item.get("confidence")
        similarity = item.get("similarity")
        lines.append(
            f"- {category}/{key}: {value} "
            f"(confidence={float(confidence or 0.0):.2f}, similarity={float(similarity or 0.0):.2f})"
        )
    return "\n".join(lines)


async def _build_memory_context(
    *,
    jwt: str,
    user_id: str,
    messages: list[dict[str, str]],
    fact_profile: dict | None,
    fact_items: list | None,
    active_trends: list,
) -> str | None:
    profile_context = build_profile_context(fact_profile)
    if profile_context and len(profile_context) > 200:
        profile_context = profile_context[:200] + "窶ｦ"

    # Phase A5: this used to be gated on settings.local_llm_enabled, with a
    # non-vector top-N-facts fallback for OpenAI-embedding mode, because
    # generate_embedding() returned [] whenever LOCAL_LLM_ENABLED=false.
    # generate_embedding() now falls back to OpenAI embeddings itself
    # (see memory_search.py), so real similarity search works in both modes
    # and this branch is unconditional. LOCAL_LLM_ENABLED=true behavior is
    # unchanged — this is exactly its old branch, just no longer gated.
    relevant_context = None
    latest_user_text = _latest_user_content(messages)
    if latest_user_text:
        try:
            relevant = await search_relevant_memories(
                latest_user_text,
                user_id,
                threshold=0.7,
                limit=5,
                jwt=jwt,
            )
            relevant_context = _build_relevant_memories_context(relevant)
        except Exception:
            logger.exception("orchestrator: relevant memory search failed")
    if relevant_context and profile_context:
        return profile_context + "\n\n" + relevant_context
    if relevant_context:
        return relevant_context
    return profile_context


# ─── Session continuity: cross-thread recent-log window (Phase A1) ───────────
#
# The schedule-agent (chat.py) resets `previous_response_id` to None on every
# request, so conversation continuity never relies on OpenAI's own response
# chaining — it is built explicitly here instead. This lets continuity span
# multiple threads (thread A's tail carries into thread B), which a linear
# previous_response_id chain could never do. See
# docs/sigmaris/phase_a1_report.md for the full design rationale.


def _extract_text_from_parts(parts: list[dict[str, Any]] | None) -> str:
    if not parts:
        return ""
    texts = [
        str(part.get("text", "")).strip()
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text" and str(part.get("text", "")).strip()
    ]
    return "\n".join(texts).strip()


def _window_rows_to_messages(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Convert chat_messages rows (parts-based) into the simple role/content
    shape the orchestrator and schedule-agent already use."""
    result: list[dict[str, str]] = []
    for row in rows:
        role = row.get("role")
        if role not in ("user", "assistant"):
            continue
        content = _extract_text_from_parts(row.get("parts"))
        if not content:
            continue
        result.append({"role": role, "content": content})
    return result


def _latest_user_message(messages: list[dict[str, str]]) -> dict[str, str] | None:
    for message in reversed(messages):
        if message.get("role") == "user" and str(message.get("content") or "").strip():
            return {"role": "user", "content": str(message["content"])}
    return None


async def _ensure_chat_thread(jwt: str, thread_id: str) -> None:
    """Make sure a chat_threads row exists for thread_id before the
    schedule-agent is asked to persist messages against it — chat.py raises
    if the thread row is missing. Tolerates a concurrent create() racing this
    check by re-checking once before giving up."""
    existing = await get_chat_thread(jwt, thread_id)
    if existing is not None:
        return
    try:
        await create_chat_thread(jwt, thread_id=thread_id)
    except Exception:
        recheck = await get_chat_thread(jwt, thread_id)
        if recheck is None:
            raise


async def _prepare_session_messages(
    *,
    jwt: str,
    thread_id: str | None,
    messages: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]], bool]:
    """Resolve the effective thread_id, build the cross-thread recent-log
    window, and decide whether this call should persist to chat_messages.

    Returns (effective_thread_id, messages_to_send, persist_thread).

    Design note: the incoming `messages` array is the caller's own
    thread-local history (frontend/WearOS-maintained). Rather than sending
    that alongside the DB-backed window (which would duplicate content) or
    discarding it outright (which would drop the just-typed message that
    isn't persisted yet), only its latest user turn is kept and appended
    after the cross-thread window. See phase_a1_report.md section 1 for why
    this was chosen over the alternatives.
    """
    effective_thread_id = thread_id or str(uuid.uuid4())
    persist_thread = True
    try:
        await _ensure_chat_thread(jwt, effective_thread_id)
    except Exception:
        logger.exception(
            "orchestrator: failed to ensure chat_thread id=%s — falling back to no persistence for this call",
            effective_thread_id,
        )
        persist_thread = False

    window_rows = await _timed(
        get_recent_messages_across_threads(jwt, limit=settings.sigmaris_recent_message_window),
        timeout=3.0,
        default=[],
        label="recent_message_window",
    )
    window_messages = _window_rows_to_messages(window_rows or [])
    latest_user = _latest_user_message(messages)

    combined = window_messages + ([latest_user] if latest_user else [])
    if not combined:
        # Cold start (no history yet) or window fetch failed and no user
        # message was found — fall back to whatever the caller sent so the
        # turn is never silently dropped.
        combined = messages

    return effective_thread_id, combined, persist_thread


# ─── Background tasks ─────────────────────────────────────────────────────────


async def _cognitive_layer_bg(
    *,
    invocation_id: str,
    thread_id: str | None,
    turn_messages: list[dict[str, str]],
    fact_items: list[dict[str, Any]] | None,
) -> None:
    """Fire-and-forget: detect+record real decisions, and nudge internal
    state, after each chat turn. Replaces the old unconditional generic
    "chat_turn" log entry (Phase A3) — detect_and_record_decision() only
    writes a row when the turn actually contained a decision or policy
    change."""
    try:
        from app.services.decision_log import detect_and_record_decision  # noqa: PLC0415
        from app.services.internal_state import get_internal_state, update_internal_state  # noqa: PLC0415

        await detect_and_record_decision(
            messages=turn_messages,
            fact_items=fact_items,
            thread_id=thread_id,
            invocation_id=invocation_id,
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

    persona = load_persona()
    agent = get_schedule_agent()

    # Auth + stable context in one parallel gather, then facts after user_id is known.
    user, fact_profile, self_model, active_trends, session = await asyncio.gather(
        _timed(get_current_user(jwt), timeout=8.0),
        _cached_user_profile(jwt),
        _cached_self_model(),
        _cached_active_trends(jwt),
        _prepare_session_messages(jwt=jwt, thread_id=thread_id, messages=messages),
        return_exceptions=False,
    )
    if not user:
        raise RuntimeError("Failed to authenticate user (timeout or error).")
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise RuntimeError("Authenticated Supabase user did not include an id.")
    fact_items = await _cached_fact_items(jwt, user_id)
    effective_thread_id, session_messages, persist_thread = session

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

    profile_context = await _build_memory_context(
        jwt=jwt,
        user_id=user_id,
        messages=messages,
        fact_profile=fact_profile,
        fact_items=fact_items,
        active_trends=active_trends,
    )

    call_name = extract_call_name(fact_profile) or _user_display_name(user)
    self_model_context = _build_self_model_context(self_model)

    try:
        schedule_result = await call_schedule_agent(
            agent=agent,
            jwt=jwt,
            google_access_token=google_access_token,
            google_refresh_token=google_refresh_token,
            messages=session_messages,
            thread_id=effective_thread_id,
            invocation_id=invocation_id,
            reason=f"orchestrator:{invocation_id}:{reason}",
            user_profile_context=profile_context,
            self_model_context=self_model_context,
            persist_thread=persist_thread,
        )
        if CONFIRMATION_MARKER_RE.search(schedule_result.text):
            # See the streaming variant for the full rationale: persona
            # rewriting has no guarantee of preserving invisible marker
            # markup, so pending-confirmation messages skip it entirely.
            response_text = replace_forbidden_assistant_names(schedule_result.text)
            used_fallback = False
            guard_violations: tuple[str, ...] = ()
        else:
            rewrite = await rewrite_with_persona(
                source=schedule_result.text,
                persona=persona,
                user_name=call_name,
            )
            response_text = replace_forbidden_assistant_names(rewrite.text)
            used_fallback = rewrite.used_fallback
            guard_violations = rewrite.guard_violations
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
        status="completed_with_fallback" if used_fallback else "completed",
        response_summary={
            "scheduleMessageId": schedule_result.message_id,
            "usedFallback": used_fallback,
            "guardViolations": list(guard_violations),
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
            get_inquiry_question(jwt, full_messages_so_far), timeout=2.0
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

    # Fire-and-forget: cognitive layer (decision detection + internal state update).
    # Scoped to just this turn (not the full cross-thread window) so an old
    # exchange still sitting in context isn't re-detected as "a new decision"
    # on every later turn.
    latest_user = _latest_user_message(messages)
    turn_messages = ([latest_user] if latest_user else []) + [
        {"role": "assistant", "content": response_text}
    ]
    asyncio.create_task(
        _cognitive_layer_bg(
            invocation_id=invocation_id,
            thread_id=effective_thread_id,
            turn_messages=turn_messages,
            fact_items=fact_items,
        ),
        name=f"cognitive_layer:{invocation_id}",
    )

    # Invalidate context cache after response so next turn picks up any new facts
    # (only invalidate facts — profile and self_model change less frequently)
    _cache.pop(f"facts:{user_id}", None)

    return {
        "ok": True,
        "text": response_text,
        "thread_id": schedule_result.thread_id,
        "invocation_id": invocation_id,
        "agent_id": agent.agent_id,
        "used_fallback": used_fallback,
    }


async def run_orchestrator_chat_stream(
    *,
    jwt: str,
    google_access_token: str | None,
    google_refresh_token: str | None,
    messages: list[dict[str, str]],
    thread_id: str | None,
    request_context: dict[str, Any] | None,
) -> AsyncGenerator[OrchestratorStreamEvent, None]:
    started_at = time.monotonic()
    invocation_id = str(uuid.uuid4())

    persona = load_persona()
    agent = get_schedule_agent()

    # Auth + stable context in one parallel gather, then facts after user_id is known.
    user, fact_profile, self_model, active_trends, session = await asyncio.gather(
        _timed(get_current_user(jwt), timeout=8.0),
        _cached_user_profile(jwt),
        _cached_self_model(),
        _cached_active_trends(jwt),
        _prepare_session_messages(jwt=jwt, thread_id=thread_id, messages=messages),
        return_exceptions=False,
    )
    if not user:
        raise RuntimeError("Failed to authenticate user (timeout or error).")
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise RuntimeError("Authenticated Supabase user did not include an id.")
    fact_items = await _cached_fact_items(jwt, user_id)
    effective_thread_id, session_messages, persist_thread = session

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
        target_endpoint=agent.chat_endpoint.replace("/complete", "/stream"),
        reason=reason,
        request_summary={
            "messageCount": len(messages),
            "latestRole": messages[-1]["role"],
            "hasGoogleAccessToken": bool(google_access_token),
            "hasGoogleRefreshToken": bool(google_refresh_token),
            "stream": True,
        },
        persona_version=persona.version,
        persona_hash=persona.sha256,
    )
    audit_row_id = str(audit_row["id"])

    profile_context = build_profile_context(fact_profile)
    if profile_context and len(profile_context) > 200:
        profile_context = profile_context[:200] + "窶ｦ"

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

    profile_context = await _build_memory_context(
        jwt=jwt,
        user_id=user_id,
        messages=messages,
        fact_profile=fact_profile,
        fact_items=fact_items,
        active_trends=active_trends,
    )

    call_name = extract_call_name(fact_profile) or _user_display_name(user)
    self_model_context = _build_self_model_context(self_model)
    schedule_text = ""
    returned_thread_id = effective_thread_id
    schedule_message_id: str | None = None
    used_fallback = False
    guard_violations: tuple[str, ...] = ()
    response_text = ""

    try:
        async for event in call_schedule_agent_stream(
            agent=agent,
            jwt=jwt,
            google_access_token=google_access_token,
            google_refresh_token=google_refresh_token,
            messages=session_messages,
            thread_id=effective_thread_id,
            invocation_id=invocation_id,
            reason=f"orchestrator:{invocation_id}:{reason}",
            user_profile_context=profile_context,
            self_model_context=self_model_context,
            persist_thread=persist_thread,
        ):
            if event.tool_event:
                yield OrchestratorStreamEvent(tool_event=event.tool_event, invocation_id=invocation_id)
            if event.delta:
                schedule_text += event.delta
            if event.done:
                returned_thread_id = event.thread_id or returned_thread_id
                schedule_message_id = event.message_id

        if not schedule_text.strip():
            raise RuntimeError("Schedule agent stream returned an empty response.")

        if CONFIRMATION_MARKER_RE.search(schedule_text):
            # A pending-confirmation marker (<!-- shiftpilot-confirmation {...} -->)
            # is invisible UI metadata, not prose. Persona rewriting is an LLM
            # tone-pass with no instruction to preserve non-visible markup, and
            # response_guard's mechanical checks only catch its loss by
            # coincidence (e.g. if the marker's JSON happens to contain a
            # number). Skip the rewrite entirely for these messages so the
            # confirmation button flow can't be silently corrupted.
            response_text = replace_forbidden_assistant_names(schedule_text)
            yield OrchestratorStreamEvent(delta=response_text, invocation_id=invocation_id)
            used_fallback = False
            guard_violations = ()
        else:
            async for rewrite_event in rewrite_with_persona_stream(
                source=schedule_text,
                persona=persona,
                user_name=call_name,
            ):
                if rewrite_event.delta:
                    delta = replace_forbidden_assistant_names(rewrite_event.delta)
                    response_text += delta
                    yield OrchestratorStreamEvent(delta=delta, invocation_id=invocation_id)
                if rewrite_event.done:
                    used_fallback = rewrite_event.used_fallback
                    guard_violations = rewrite_event.guard_violations
                    if rewrite_event.text is not None and used_fallback:
                        response_text = replace_forbidden_assistant_names(rewrite_event.text)

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
        status="completed_with_fallback" if used_fallback else "completed",
        response_summary={
            "scheduleMessageId": schedule_message_id,
            "usedFallback": used_fallback,
            "guardViolations": list(guard_violations),
            "responseLength": len(response_text),
            "stream": True,
        },
        error_code=None,
        duration_ms=duration_ms,
    )

    try:
        from app.services.active_inquiry import get_inquiry_question  # noqa: PLC0415
        full_messages_so_far = list(messages) + [{"role": "assistant", "content": response_text}]
        inquiry = await asyncio.wait_for(
            get_inquiry_question(jwt, full_messages_so_far), timeout=2.0
        )
        if inquiry:
            inquiry_delta = "\n\n" + inquiry
            response_text += inquiry_delta
            yield OrchestratorStreamEvent(delta=inquiry_delta, invocation_id=invocation_id)
    except (asyncio.TimeoutError, Exception):
        pass

    from app.services.memory_extractor import extract_from_conversation  # noqa: PLC0415
    full_messages = list(messages) + [{"role": "assistant", "content": response_text}]
    asyncio.create_task(
        extract_from_conversation(messages=full_messages, jwt=jwt),
        name=f"memory_extract:{invocation_id}",
    )
    latest_user = _latest_user_message(messages)
    turn_messages = ([latest_user] if latest_user else []) + [
        {"role": "assistant", "content": response_text}
    ]
    asyncio.create_task(
        _cognitive_layer_bg(
            invocation_id=invocation_id,
            thread_id=effective_thread_id,
            turn_messages=turn_messages,
            fact_items=fact_items,
        ),
        name=f"cognitive_layer:{invocation_id}",
    )
    _cache.pop(f"facts:{user_id}", None)

    yield OrchestratorStreamEvent(
        done=True,
        thread_id=returned_thread_id,
        invocation_id=invocation_id,
        agent_id=agent.agent_id,
        used_fallback=used_fallback,
        guard_violations=guard_violations,
    )
