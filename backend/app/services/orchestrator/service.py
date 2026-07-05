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
from app.services.abstention_feedback import get_threshold_adjustment, record_pending_hedge
from app.services.goal_alignment import get_active_goal_alignment_flags, mark_pending_surfaced
from app.services.knowledge_graph import build_entity_hint, get_entities_and_relations
from app.services.memory_confidence import classify_confidence_tier, confidence_guidance_note
from app.services.memory_compression import compress_memories_if_needed
from app.services.multihop_search import search_with_decomposition
from app.services.decision_log import get_active_preference_patterns
from app.services.self_model import get_self_model
from app.services.topic_tracker import get_current_and_previous_topic
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


async def _cached_preference_patterns() -> list[dict[str, Any]]:
    hit, val = _cache_get("preference_patterns")
    if hit:
        return val
    result = await _timed(
        get_active_preference_patterns(limit=5), timeout=3.0, default=[], label="preference_patterns"
    )
    _cache_set("preference_patterns", result)
    return result or []


async def _cached_goal_alignment_flags() -> list[dict[str, Any]]:
    hit, val = _cache_get("goal_alignment_flags")
    if hit:
        return val
    result = await _timed(
        get_active_goal_alignment_flags(limit=1), timeout=3.0, default=[], label="goal_alignment_flags"
    )
    _cache_set("goal_alignment_flags", result)
    return result or []


async def _cached_entities_and_relations() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hit, val = _cache_get("entities_and_relations")
    if hit:
        return val
    result = await _timed(
        get_entities_and_relations(), timeout=3.0, default=([], []), label="entities_and_relations"
    )
    _cache_set("entities_and_relations", result)
    return result or ([], [])


async def _cached_current_and_previous_topic() -> tuple[dict | None, dict | None]:
    hit, val = _cache_get("topic")
    if hit:
        return val
    result = await _timed(
        get_current_and_previous_topic(), timeout=3.0, default=(None, None), label="topic"
    )
    _cache_set("topic", result)
    return result or (None, None)


async def _cached_threshold_adjustment() -> float:
    hit, val = _cache_get("abstention_threshold_adjustment")
    if hit:
        return val
    result = await _timed(
        get_threshold_adjustment(), timeout=3.0, default=0.0, label="abstention_threshold_adjustment"
    )
    _cache_set("abstention_threshold_adjustment", result)
    return result if result is not None else 0.0


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


def _format_freshness_note(last_reflected_at: Any) -> str:
    """Day-granularity "how stale is this" label, shared by self_model's
    identity_statement (Phase: ShiftPilotAI-naming incident fix) and B14's
    preference patterns.

    identity_statement is written by a ~daily self-reflection cycle
    (heartbeat.py's 24h cooldown), and preference patterns by a weekly
    batch job (proactive/scheduler.py's preference_pattern_extract) — both
    were, before their respective fixes, injected into every turn with zero
    indication of when they were written, so the model had no way to tell
    stale content from something that "just happened". Deliberately rounded
    to whole days (JST calendar-day difference, not hours/minutes):
    base_system already isn't turn-stable for OpenAI's prefix cache because
    of the fact-memory RAG portion (see chat_prompts.py's ordering comment),
    so this adds no *additional* cache churn beyond what already exists —
    but keeping it at day-resolution rather than finer avoids making that
    pre-existing situation any worse.
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
    freshness_note = _format_freshness_note(model.get("last_reflected_at"))
    goals = model.get("current_goals") or []
    lines = [f"[シグマリス自己認識] {freshness_note}\n{identity_short}"]
    if goals:
        goal_str = "・".join(str(g) for g in goals[:3])  # max 3 goals
        lines.append(f"目標: {goal_str}")
    return "\n".join(lines)


# Phase B14: below this many supporting decisions, a pattern is treated as
# persona.md section 5's "仮説層" (low confidence — must hedge, e.g.
# 「もしかしたら〜かもしれません」). At or above it, "傾向層" (soft
# assertion allowed, e.g. 「〜な傾向がありますね」) — still never a flat
# assertion ("事実層"), since this is always inferred, never confirmed
# outright by 海星さん. Kept low (evidence_count already requires >= 2 to
# be stored at all — see decision_log.py's _MIN_SUPPORTING_DECISIONS) so
# most freshly-detected patterns start in the more heavily-hedged tier.
_PREFERENCE_PATTERN_HYPOTHESIS_MAX_EVIDENCE = 3


def _build_preference_patterns_context(patterns: list[dict[str, Any]] | None) -> str | None:
    if not patterns:
        return None
    lines = [
        "[海星さんの判断傾向(推測・参考情報)]",
        "以下は過去の決定記録から推測された傾向であり、断定してはいけません。"
        "根拠件数が少ないものは「もしかしたら〜かもしれません」のように必ずヘッジし、"
        "根拠が十分にあるものでも「〜な傾向がありますね」のように柔らかく言い切るに留め、"
        "「あなたはこういう人だから」と決めつける口調は使わないこと。",
    ]
    for pattern in patterns:
        statement = str(pattern.get("pattern_statement") or "").strip()
        if not statement:
            continue
        evidence_count = int(pattern.get("evidence_count") or 0)
        tier = (
            "仮説層(要ヘッジ)"
            if evidence_count <= _PREFERENCE_PATTERN_HYPOTHESIS_MAX_EVIDENCE
            else "傾向層(柔らかい言い切り可)"
        )
        freshness_note = _format_freshness_note(pattern.get("last_confirmed_at"))
        lines.append(f"- {statement} (根拠決定{evidence_count}件、{tier}、{freshness_note})")

    return "\n".join(lines) if len(lines) > 2 else None


# Phase B16: unlike this file's other _build_*_context helpers, this one
# has a side effect (mark_pending_surfaced) — deliberate: the moment a flag
# is actually included in a prompt is the moment its 14-day surface
# cooldown (goal_alignment.py's _SURFACE_COOLDOWN_DAYS) should start,
# and that moment is exactly "this function ran with a non-empty flags
# list", nowhere else. The actual DB write is deferred to _cognitive_
# layer_bg's fire-and-forget flush (flush_pending_surfaced_flags below),
# so this function itself makes no I/O call and adds no response-path
# latency.
def _build_goal_alignment_context(flags: list[dict[str, Any]] | None) -> str | None:
    if not flags:
        return None
    flag = flags[0]  # at most one per turn — a single gentle nudge, never a list of grievances
    statement = str(flag.get("flag_statement") or "").strip()
    if not statement:
        return None

    mark_pending_surfaced(flag.get("id"))

    lines = [
        "[長期ゴールとの整合性について(参考情報)]",
        "以下は、直近の決定・話題が長期的な目標から乖離している可能性がある、と"
        "いう観察です。persona.md 9章(制止する時のルール)に厳密に従い、「ちょ"
        "っと待ってください。一度整理しましょう」「その前に確認したいことがあり"
        "ます」のような、確認・提案の形でのみ触れてよいものです。「却下」という"
        "言い方や、断定的に「目標からズレています」と指摘することは絶対にしない"
        "でください。会話の流れに合わない場合は、無理に触れる必要はありません。",
        f"- {statement}",
    ]
    return "\n".join(lines)


# Phase B6: distinct from _build_trends_context below, despite both
# formatting a "[...]" block — user_trend_items (trend_analyzer.py) is an
# unrelated feature (recurring lifestyle/behavior trends inferred over
# weeks) that happens to also use a field named topic_label on its own
# table. sigmaris_topic_log is instead a flat, turn-by-turn running log of
# "what's being discussed right now" — see topic_tracker.py's module
# docstring for the full role-separation writeup (Phase A1 vs B2 vs this).
def _build_topic_context(
    current_topic: dict[str, Any] | None,
    previous_topic: dict[str, Any] | None,
) -> str | None:
    if not current_topic:
        return None
    current_label = str(current_topic.get("topic_label") or "").strip()
    if not current_label:
        return None
    lines = ["[話題の推移(参考情報)]", f"現在の話題: {current_label}"]
    if previous_topic:
        previous_label = str(previous_topic.get("topic_label") or "").strip()
        if previous_label:
            lines.append(f"直前の話題: {previous_label}")
    lines.append(
        "必要だと感じた場合のみ、話題の切り替わりに自然に触れてよい"
        "(例:「さっきまで〜の話をしてましたね」)。毎回言及する必要はない。"
    )
    return "\n".join(lines)


# Phase B7: reuses the same current/previous topic rows _build_topic_
# context() above already fetched (via _cached_current_and_previous_topic)
# rather than issuing a second, deeper topic_tracker.get_recent_topics()
# call — B6 only ever holds 2 meaningfully-labeled rows in this codepath
# anyway at this point in the session, and this hint is a lightweight,
# optional disambiguation aid for multihop_search.decompose_query(), not a
# strict dependency (see phase_b7_report.md section 1 for why a second
# fetch wasn't added).
def _topic_labels_for_hint(
    current_topic: dict[str, Any] | None,
    previous_topic: dict[str, Any] | None,
) -> list[str] | None:
    labels = []
    for topic in (previous_topic, current_topic):
        if not topic:
            continue
        label = str(topic.get("topic_label") or "").strip()
        if label:
            labels.append(label)
    return labels or None


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
    recent_topic_labels: list[str] | None = None,
    thread_id: str | None = None,
    threshold_adjustment: float = 0.0,
    entities: list[dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
) -> str | None:
    profile_context = build_profile_context(fact_profile)
    if profile_context and len(profile_context) > 200:
        profile_context = profile_context[:200] + "窶ｦ"

    # Incident fix (docs/sigmaris/incident_facts_context_overwrite_fix.md):
    # this function's return value used to *replace* the caller's own
    # profile_context wholesale, silently discarding the top-5-importance
    # facts_ctx and top-3 trends_ctx blocks the caller had just built and
    # concatenated onto it moments earlier. fact_items/active_trends were
    # already accepted as parameters here (unused) — building facts_ctx and
    # trends_ctx directly inside this function, on the one profile_context
    # this function actually returns, is what those parameters were for.
    # facts_ctx (static top-5 by importance x confidence) and relevant_context
    # below (query-specific RAG retrieval) are deliberately both kept: they
    # answer different questions ("what does Sigmaris always consider
    # important" vs. "what's relevant to this specific question") and are
    # not redundant selections over the same data, even though the same
    # individual fact could occasionally appear in both.
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

    # Phase A5: this used to be gated on settings.local_llm_enabled, with a
    # non-vector top-N-facts fallback for OpenAI-embedding mode, because
    # generate_embedding() returned [] whenever LOCAL_LLM_ENABLED=false.
    # generate_embedding() now falls back to OpenAI embeddings itself
    # (see memory_search.py), so real similarity search works in both modes
    # and this branch is unconditional. LOCAL_LLM_ENABLED=true behavior is
    # unchanged — this is exactly its old branch, just no longer gated.
    #
    # Phase B7: search_relevant_memories() is now called indirectly via
    # search_with_decomposition(), which transparently decomposes this
    # query into sub-queries first when the LLM judges it necessary (a
    # question spanning multiple distinct facts) and otherwise falls
    # through to the exact same single-query call this used to make
    # directly — see multihop_search.py's module docstring.
    relevant_context = None
    latest_user_text = _latest_user_content(messages)
    if latest_user_text:
        try:
            # Phase B9: pure substring matching against the (TTL-cached)
            # entity/relation snapshot — no LLM call, no I/O here. Only
            # ever produces a non-None hint when the query actually
            # mentions a known entity name.
            entity_hint = build_entity_hint(entities or [], relations or [], latest_user_text)
            relevant, was_decomposed, time_sensitive = await search_with_decomposition(
                latest_user_text,
                user_id,
                threshold=0.7,
                limit=5,
                jwt=jwt,
                recent_topic_labels=recent_topic_labels,
                entity_hint=entity_hint,
            )
            # Phase B11: calibrated abstention — reuses B7's/B8's already-
            # computed multihop/time-sensitive judgments and each result's
            # own similarity field, at zero additional LLM calls (see
            # memory_confidence.py's module docstring for the full
            # rationale). Classified on the pristine (pre-compression)
            # results — compression below only ever shortens value text,
            # never touches similarity, but keeping this ordering explicit
            # avoids the two features' concerns ever becoming coupled.
            tier = classify_confidence_tier(
                relevant,
                is_multihop=was_decomposed,
                is_time_sensitive=time_sensitive,
                threshold_adjustment=threshold_adjustment,
            )
            # Phase B15: record that this thread just received a hedged
            # answer so the next turn's fire-and-forget cognitive layer
            # (_cognitive_layer_bg) can classify 海星さん's reply to it —
            # see abstention_feedback.py's module docstring.
            if tier != "confident":
                record_pending_hedge(thread_id)
            # Phase B12: rule-based post-retrieval compression — only
            # triggers when the whole block is estimated to exceed a token
            # budget, and even then leaves high-importance facts (Phase
            # B17's importance_score) untouched. See memory_compression.py's
            # module docstring for why this is rule-based rather than an
            # LLM summarization call.
            compressed_relevant, _was_compressed = compress_memories_if_needed(
                relevant, query=latest_user_text
            )
            relevant_context = _build_relevant_memories_context(compressed_relevant)
            guidance = confidence_guidance_note(tier)
            if guidance:
                relevant_context = f"{relevant_context}\n{guidance}" if relevant_context else guidance
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


async def _extract_facts_bg(
    *,
    messages: list[dict[str, str]],
    jwt: str,
    user_id: str,
    thread_id: str | None,
    invocation_id: str,
) -> None:
    """Fire-and-forget: extract memorable facts from this conversation turn,
    then invalidate the per-user facts cache only after extraction has
    actually finished writing.

    Previously the cache was popped synchronously in the main flow right
    after dispatching extract_from_conversation() via asyncio.create_task —
    before extraction had actually run, let alone written anything. That
    left a window where a request arriving shortly after the response
    could still see the pre-extraction cached facts despite the "invalidate
    after this turn" comment implying otherwise. Wrapping the call and
    popping the cache in this function's own finally block (mirroring
    _cognitive_layer_bg's "topic" cache invalidation below, added in Phase
    B6) closes that gap: the pop can only happen once the write attempt has
    genuinely completed, success or failure."""
    from app.services.memory_extractor import extract_from_conversation  # noqa: PLC0415
    try:
        await extract_from_conversation(
            messages=messages,
            jwt=jwt,
            thread_id=thread_id,
            invocation_id=invocation_id,
        )
    except Exception:
        # extract_from_conversation() is documented to never raise (it
        # returns [] on any internal failure) — this is a second layer of
        # protection only, matching _cognitive_layer_bg's own belt-and-
        # suspenders try/except below.
        logger.exception("extract_facts_bg: failed for invocation=%s", invocation_id)
    finally:
        _cache.pop(f"facts:{user_id}", None)


async def _cognitive_layer_bg(
    *,
    invocation_id: str,
    thread_id: str | None,
    turn_messages: list[dict[str, str]],
    fact_items: list[dict[str, Any]] | None,
    jwt: str,
) -> None:
    """Fire-and-forget: detect+record real decisions and episodic memory,
    reflect any pending memory re-confirmation (Phase B3) and pending
    abstention-hedge reaction (Phase B15), persist any pending goal-
    alignment-flag surface timestamp (Phase B16), and nudge internal state,
    after each chat turn. Replaces the old unconditional generic
    "chat_turn" log entry (Phase A3) — detect_and_record_decision() only
    writes a row when the turn actually contained a decision or policy
    change, and (Phase B2) detect_and_record_episode() only writes a row
    when the turn contained an event worth remembering episodically. All
    six calls run concurrently since they're independent. jwt is only
    needed by reflect_pending_confirmation() (it may write to
    user_fact_items through the per-user RLS path) —
    decision/episode/topic/abstention-reaction detection and the goal-
    alignment flush use service-role access and don't touch it."""
    try:
        from app.services.abstention_feedback import reflect_abstention_reaction  # noqa: PLC0415
        from app.services.active_inquiry import reflect_pending_confirmation  # noqa: PLC0415
        from app.services.decision_log import detect_and_record_decision  # noqa: PLC0415
        from app.services.experience_layer import detect_and_record_episode  # noqa: PLC0415
        from app.services.goal_alignment import flush_pending_surfaced_flags  # noqa: PLC0415
        from app.services.internal_state import get_internal_state, update_internal_state  # noqa: PLC0415
        from app.services.topic_tracker import detect_and_record_topic_transition  # noqa: PLC0415

        await asyncio.gather(
            detect_and_record_decision(
                messages=turn_messages,
                fact_items=fact_items,
                thread_id=thread_id,
                invocation_id=invocation_id,
            ),
            detect_and_record_episode(
                messages=turn_messages,
                thread_id=thread_id,
                invocation_id=invocation_id,
            ),
            reflect_pending_confirmation(
                thread_id=thread_id,
                turn_messages=turn_messages,
                jwt=jwt,
            ),
            detect_and_record_topic_transition(
                messages=turn_messages,
                thread_id=thread_id,
                invocation_id=invocation_id,
            ),
            reflect_abstention_reaction(
                thread_id=thread_id,
                turn_messages=turn_messages,
                invocation_id=invocation_id,
            ),
            flush_pending_surfaced_flags(),
        )

        state = await get_internal_state()
        await update_internal_state(
            curiosity=min(1.0, float(state.get("curiosity", 0.5)) + 0.01),
            stability=min(1.0, float(state.get("stability", 0.8)) + 0.005),
        )
    except Exception:
        logger.exception("cognitive_layer_bg: failed for invocation=%s", invocation_id)
    finally:
        # Invalidate regardless of gather outcome (partial failure of one
        # of the six calls above must not leave a stale topic/threshold-
        # adjustment/goal-alignment-flags value cached for the rest of
        # _CACHE_TTL) — same finally-based invalidation approach
        # _extract_facts_bg above uses for the facts cache.
        _cache.pop("topic", None)
        _cache.pop("abstention_threshold_adjustment", None)
        _cache.pop("goal_alignment_flags", None)


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
    user, fact_profile, self_model, preference_patterns, topic_state, threshold_adjustment, goal_alignment_flags, entities_and_relations, active_trends, session = await asyncio.gather(
        _timed(get_current_user(jwt), timeout=8.0),
        _cached_user_profile(jwt),
        _cached_self_model(),
        _cached_preference_patterns(),
        _cached_current_and_previous_topic(),
        _cached_threshold_adjustment(),
        _cached_goal_alignment_flags(),
        _cached_entities_and_relations(),
        _cached_active_trends(jwt),
        _prepare_session_messages(jwt=jwt, thread_id=thread_id, messages=messages),
        return_exceptions=False,
    )
    entities, relations = entities_and_relations
    if not user:
        raise RuntimeError("Failed to authenticate user (timeout or error).")
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise RuntimeError("Authenticated Supabase user did not include an id.")
    fact_items = await _cached_fact_items(jwt, user_id)
    effective_thread_id, session_messages, persist_thread = session
    current_topic, previous_topic = topic_state

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

    # Build lightweight context (profile 200 chars, facts top 5, trends top 3,
    # then Phase B1+'s query-relevant RAG results on top). All of this is now
    # built inside _build_memory_context() itself — see the incident fix
    # note in that function's body (docs/sigmaris/
    # incident_facts_context_overwrite_fix.md) for why facts_ctx/trends_ctx
    # used to be built here, then silently discarded by this same
    # assignment overwriting them.
    profile_context = await _build_memory_context(
        jwt=jwt,
        user_id=user_id,
        messages=messages,
        fact_profile=fact_profile,
        fact_items=fact_items,
        active_trends=active_trends,
        recent_topic_labels=_topic_labels_for_hint(current_topic, previous_topic),
        thread_id=effective_thread_id,
        threshold_adjustment=threshold_adjustment,
        entities=entities,
        relations=relations,
    )

    call_name = extract_call_name(fact_profile) or _user_display_name(user)
    self_model_context = _build_self_model_context(self_model)
    preference_patterns_context = _build_preference_patterns_context(preference_patterns)
    topic_context = _build_topic_context(current_topic, previous_topic)
    goal_alignment_context = _build_goal_alignment_context(goal_alignment_flags)

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
            preference_patterns_context=preference_patterns_context,
            topic_context=topic_context,
            goal_alignment_context=goal_alignment_context,
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
            get_inquiry_question(jwt, full_messages_so_far, thread_id=effective_thread_id), timeout=2.0
        )
        if inquiry:
            response_text = response_text + "\n\n" + inquiry
    except (asyncio.TimeoutError, Exception):
        pass  # Never block the response for inquiry failures

    # Fire-and-forget: extract memorable facts from this conversation turn.
    # (Facts cache invalidation now happens inside _extract_facts_bg's own
    # finally block, after extraction actually completes — see that
    # function's docstring for why popping it here in the main flow used to
    # be too early.)
    full_messages = list(messages) + [{"role": "assistant", "content": response_text}]
    asyncio.create_task(
        _extract_facts_bg(
            messages=full_messages,
            jwt=jwt,
            user_id=user_id,
            thread_id=effective_thread_id,
            invocation_id=invocation_id,
        ),
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
            jwt=jwt,
        ),
        name=f"cognitive_layer:{invocation_id}",
    )

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
    user, fact_profile, self_model, preference_patterns, topic_state, threshold_adjustment, goal_alignment_flags, entities_and_relations, active_trends, session = await asyncio.gather(
        _timed(get_current_user(jwt), timeout=8.0),
        _cached_user_profile(jwt),
        _cached_self_model(),
        _cached_preference_patterns(),
        _cached_current_and_previous_topic(),
        _cached_threshold_adjustment(),
        _cached_goal_alignment_flags(),
        _cached_entities_and_relations(),
        _cached_active_trends(jwt),
        _prepare_session_messages(jwt=jwt, thread_id=thread_id, messages=messages),
        return_exceptions=False,
    )
    entities, relations = entities_and_relations
    if not user:
        raise RuntimeError("Failed to authenticate user (timeout or error).")
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise RuntimeError("Authenticated Supabase user did not include an id.")
    fact_items = await _cached_fact_items(jwt, user_id)
    effective_thread_id, session_messages, persist_thread = session
    current_topic, previous_topic = topic_state

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

    # See run_orchestrator_chat's identical comment / docs/sigmaris/
    # incident_facts_context_overwrite_fix.md — facts_ctx/trends_ctx are now
    # built inside _build_memory_context() itself, not here.
    profile_context = await _build_memory_context(
        jwt=jwt,
        user_id=user_id,
        messages=messages,
        fact_profile=fact_profile,
        fact_items=fact_items,
        active_trends=active_trends,
        recent_topic_labels=_topic_labels_for_hint(current_topic, previous_topic),
        thread_id=effective_thread_id,
        threshold_adjustment=threshold_adjustment,
        entities=entities,
        relations=relations,
    )

    call_name = extract_call_name(fact_profile) or _user_display_name(user)
    self_model_context = _build_self_model_context(self_model)
    preference_patterns_context = _build_preference_patterns_context(preference_patterns)
    topic_context = _build_topic_context(current_topic, previous_topic)
    goal_alignment_context = _build_goal_alignment_context(goal_alignment_flags)
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
            preference_patterns_context=preference_patterns_context,
            topic_context=topic_context,
            goal_alignment_context=goal_alignment_context,
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
            get_inquiry_question(jwt, full_messages_so_far, thread_id=effective_thread_id), timeout=2.0
        )
        if inquiry:
            inquiry_delta = "\n\n" + inquiry
            response_text += inquiry_delta
            yield OrchestratorStreamEvent(delta=inquiry_delta, invocation_id=invocation_id)
    except (asyncio.TimeoutError, Exception):
        pass

    full_messages = list(messages) + [{"role": "assistant", "content": response_text}]
    asyncio.create_task(
        _extract_facts_bg(
            messages=full_messages,
            jwt=jwt,
            user_id=user_id,
            thread_id=effective_thread_id,
            invocation_id=invocation_id,
        ),
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
            jwt=jwt,
        ),
        name=f"cognitive_layer:{invocation_id}",
    )

    yield OrchestratorStreamEvent(
        done=True,
        thread_id=returned_thread_id,
        invocation_id=invocation_id,
        agent_id=agent.agent_id,
        used_fallback=used_fallback,
        guard_violations=guard_violations,
    )
