from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.app_chat_data import (
    create_chat_thread,
    get_chat_thread,
    get_earliest_message_at,
    get_recent_messages_across_threads,
)
from app.services.orchestrator.agent_registry import get_schedule_agent
from app.services.orchestrator.audit import finish_invocation, start_invocation
from app.services.orchestrator.persona_loader import load_persona
from app.services.orchestrator.persona_loader import PersonaDocument
from app.services.orchestrator.response_guard import (
    compare_response_to_tool_outputs,
    replace_forbidden_assistant_names,
)
from app.services.orchestrator.schedule_agent_client import call_schedule_agent, call_schedule_agent_stream
from app.services.supabase_rest import get_current_user
from app.services.abstention_feedback import get_threshold_adjustment, record_pending_hedge
from app.services.dissent import (
    _BOLDNESS_PUSHBACK_THRESHOLD,
    get_dissent_boldness_adjustment,
    record_pending_dissent,
    reflect_dissent_reaction,
    select_dissent_candidate,
)
from app.services.goal_alignment import mark_pending_surfaced
from app.services.knowledge_graph import build_entity_hint
from app.services.live_detail_masking import build_masked_memory_preview
from app.services.live_event_details import persist_live_event_detail_bg
from app.services.live_events import emit_live_event
from app.services.memory_confidence import classify_confidence_tier, confidence_guidance_note
from app.services.memory_compression import compress_memories_if_needed
from app.services.memory_snapshot import get_memory_snapshot
from app.services.multihop_search import search_with_decomposition
from app.services.self_model import get_self_model
from app.services.temporal_parsing import extract_diary_date_range
from app.services.user_fact_data import (
    build_facts_context,
    build_profile_context,
    extract_call_name,
    get_events_in_date_range,
    get_fact_items_for_user,
    get_fact_items,
    get_user_profile,
    mark_facts_mentioned,
    select_top_facts,
)

logger = logging.getLogger(__name__)

# ─── 5-minute TTL cache for expensive pre-response DB reads ──────────────────
_CACHE_TTL = 300.0  # seconds
_recently_surfaced_goal_flag_ids: set[str] = set()

_cache: dict[str, tuple[float, Any]] = {}  # key → (timestamp, value)

# Self-3(docs/sigmaris/self_awareness_report.md): capability summaries only
# change when the weekly self_awareness_update scheduler job (proactive/
# scheduler.py) regenerates them via Self-1/Self-2 — a "quasi-fixed" cadence
# far slower than the 5-minute TTL above, which exists for data that can
# genuinely change within a single conversation (facts, active trends,
# etc.). A single process-wide key is used (not per-user) because capability
# summaries describe Sigmaris itself, not any one user's data.
_CAPABILITY_CACHE_KEY = "capability_summaries"
_CAPABILITY_CACHE_TTL = 86400.0  # 24 hours — an upper bound; the scheduler
# job also calls invalidate_capability_summary_cache() right after writing
# fresh rows, so a running process picks up new summaries immediately
# rather than waiting for this TTL to lapse.


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


def _cache_get(key: str, *, ttl: float = _CACHE_TTL) -> tuple[bool, Any]:
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0] < ttl):
        return True, entry[1]
    return False, None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


def _cache_pop_prefix(prefix: str) -> None:
    for key in list(_cache):
        if key.startswith(prefix):
            _cache.pop(key, None)


def _maybe_take_pending_inquiry(thread_id: str | None) -> str | None:
    if not settings.sigmaris_surface_inquiry_questions:
        return None
    from app.services.active_inquiry import take_pending_inquiry_question  # noqa: PLC0415

    return take_pending_inquiry_question(thread_id)


def _maybe_stash_future_inquiry(
    *,
    jwt: str,
    recent_messages: list[dict[str, str]],
    thread_id: str | None,
    invocation_id: str,
) -> None:
    if not settings.sigmaris_surface_inquiry_questions:
        return
    from app.services.active_inquiry import generate_and_stash_inquiry_question  # noqa: PLC0415

    asyncio.create_task(
        generate_and_stash_inquiry_question(
            jwt=jwt,
            recent_messages=recent_messages,
            thread_id=thread_id,
        ),
        name=f"inquiry_question:{invocation_id}",
    )


def _build_unified_persona_context(persona: PersonaDocument, user_name: str | None) -> str:
    return (
        "Sigmaris unified-generation context:\n"
        "Answer as Sigmaris directly in this first generation; no later rewrite "
        "exists in Phase BA4. Use warm, natural Japanese with practical clarity. "
        "Start by meeting the user's emotion or intent briefly, then give the "
        "useful answer, analysis, or next question. Hedge uncertainty instead "
        "of overclaiming. Keep replies concise unless the task is complex. Use "
        "the assistant name Sigmaris when naming yourself. Keep tool-derived "
        "facts exact, and preserve confirmation markers intact if present.\n\n"
        f"USER_NAME: {user_name or 'unknown'}\n"
        f"PERSONA_VERSION: {persona.version}\n"
        f"PERSONA_SHA256: {persona.sha256}"
    )


def _finalize_unified_response(
    *,
    text: str,
    tool_events: list[dict[str, Any]] | None = None,
) -> tuple[str, tuple[str, ...]]:
    response_text = replace_forbidden_assistant_names(text)
    guard = compare_response_to_tool_outputs(
        tool_events=tool_events or [],
        response_text=response_text,
    )
    if not guard.passed:
        logger.warning("unified response tool-fact guard failed: %s", guard.violations)
    return response_text, guard.violations


def _jwt_cache_key(jwt: str) -> str:
    """Phase BA2: full-jwt hash for per-user cache keys.

    _cached_user_profile/_cached_active_trends below used to key on
    `jwt[:20]` — but a standard HS256-signed JWT's header
    (`{"alg":"HS256","typ":"JWT"}`, base64url-encoded) is 36 characters on
    its own, identical for every user, so the first 20 characters of
    virtually any two JWTs from this project collide regardless of whose
    token they are. In this system's current single-tenant deployment that
    was harmless (there was never a second user to collide with), but it
    was still the wrong key derivation to leave in place, and this task's
    new get_profile_context() cache (app_profile_data.py) would have
    reproduced the same mistake if it had copied this helper instead of
    hashing the full token. See docs/sigmaris/phase_ba2_report.md."""
    return hashlib.sha256(jwt.encode("utf-8")).hexdigest()


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


async def _cached_memory_snapshot(user_id: str) -> dict[str, Any]:
    hit, val = _cache_get(f"memory_snapshot:{user_id}")
    if hit:
        return val
    result = await _timed(
        get_memory_snapshot(user_id),
        timeout=3.0,
        default={
            "preference_patterns": [],
            "topic_state": {"current": None, "previous": None},
            "goal_alignment_flags": [],
            "entities": [],
            "relations": [],
        },
        label="memory_snapshot",
    )
    snapshot = result or {}
    _cache_set(f"memory_snapshot:{user_id}", snapshot)
    return snapshot


async def _cached_threshold_adjustment() -> float:
    hit, val = _cache_get("abstention_threshold_adjustment")
    if hit:
        return val
    result = await _timed(
        get_threshold_adjustment(), timeout=3.0, default=0.0, label="abstention_threshold_adjustment"
    )
    _cache_set("abstention_threshold_adjustment", result)
    return result if result is not None else 0.0


async def _cached_dissent_boldness_adjustment() -> float:
    """Phase S-3: same TTL-cache shape as _cached_threshold_adjustment()
    above (dissent.get_dissent_boldness_adjustment() hits sigmaris_
    abstention_feedback, the same table B15's own cached wrapper reads —
    see dissent.py's module docstring for why the table is shared)."""
    hit, val = _cache_get("dissent_boldness_adjustment")
    if hit:
        return val
    result = await _timed(
        get_dissent_boldness_adjustment(), timeout=3.0, default=0.0, label="dissent_boldness_adjustment"
    )
    _cache_set("dissent_boldness_adjustment", result)
    return result if result is not None else 0.0


async def _cached_user_profile(jwt: str) -> dict | None:
    key = f"profile:{_jwt_cache_key(jwt)}"
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
    key = f"trends:{_jwt_cache_key(jwt)}"
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


async def _cached_relationship_origin_date(jwt: str) -> str | None:
    """Temporal Layer Step 3: the caller's first-ever chat_messages
    created_at, used as the "relationship origin date" for elapsed-days
    awareness. Cached on the same 5-minute TTL as the other _cached_* reads
    in this module for consistency, even though the underlying value never
    actually changes once set — the query is a single indexed limit-1 read
    on a single-tenant table, so the redundant re-fetch every 5 minutes is
    negligible, and a dedicated never-expiring cache would be one more
    caching mechanism to reason about for no measurable benefit."""
    key = f"relationship_origin:{_jwt_cache_key(jwt)}"
    hit, val = _cache_get(key)
    if hit:
        return val
    result = await _timed(get_earliest_message_at(jwt), timeout=3.0, label="relationship_origin_date")
    _cache_set(key, result)
    return result


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


# Self-3(docs/sigmaris/self_awareness_report.md): Self-1(コードベースの
# 洗い出し)・Self-2(一人称の日本語要約)が生成した`sigmaris_capability_
# summaries`を、応答生成へ選択的に注入する。他の`_build_*_context`関数
# 群と同じ「既に取得済みのデータを整形するだけ」という設計を踏襲しつ
# つ、本関数だけは非同期のDB読み取り(キャッシュ経由)も担う——
# 理由は、選択的注入(capability_summary.detect_capability_question()が一致した
# ときのみ)を行うには、「まず判定し、一致した場合にのみ取得する」という
# 順序が必要であり、他の場所で先に無条件フェッチしてから本関数へ
# 渡す設計にすると、無関係なターンでも毎回DBアクセスが発生してしまうため。
async def _cached_capability_summaries() -> list[dict[str, Any]]:
    hit, value = _cache_get(_CAPABILITY_CACHE_KEY, ttl=_CAPABILITY_CACHE_TTL)
    if hit:
        return value
    from app.services.capability_summary_store import get_capability_summaries  # noqa: PLC0415

    summaries = await get_capability_summaries()
    _cache_set(_CAPABILITY_CACHE_KEY, summaries)
    return summaries


def invalidate_capability_summary_cache() -> None:
    """proactive/scheduler.pyのself_awareness_updateジョブ呼び出し専用。
    週次でSelf-1/Self-2が新しい要約をDBへ書き込んだ直後に呼ばれ、
    _CAPABILITY_CACHE_TTL(24時間)の経過を待たず、次のターンから
    新しい要約が反映されるようにする。"""
    _cache.pop(_CAPABILITY_CACHE_KEY, None)


def _build_capability_context(summaries: list[dict[str, Any]]) -> str | None:
    if not summaries:
        return None
    lines = ["[シグマリス自身の機能一覧(自己認識)]"]
    for row in summaries:
        text = str(row.get("summary_text") or "").strip()
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines) if len(lines) > 1 else None


async def _maybe_build_capability_context(messages: list[dict[str, str]]) -> str | None:
    """最新のユーザー発話が"自分は何ができるか"に関連する質問だった場合
    にのみ、capability_context(能力要約)を取得・整形して返す(選択的
    注入、判断根拠はcapability_summary.detect_capability_question()の
    docstring参照)。無関係なターンでは、DBアクセス自体を一切行わない。"""
    from app.services.capability_summary import detect_capability_question  # noqa: PLC0415

    if not detect_capability_question(_latest_user_content(messages)):
        return None
    summaries = await _cached_capability_summaries()
    return _build_capability_context(summaries)


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

    flag_id = flag.get("id")
    if isinstance(flag_id, str):
        _recently_surfaced_goal_flag_ids.add(flag_id)
    mark_pending_surfaced(flag_id)

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


# Phase S-3: reuses B14's preference_patterns as "material for dissent" for
# the first time (docs/sigmaris/phase_s_report.md). No new pattern-
# extraction logic here — dissent.select_dissent_candidate() only picks
# among patterns B14 already produced, requiring evidence_count above the
# same 傾向層 threshold this file's _PREFERENCE_PATTERN_HYPOTHESIS_MAX_
# EVIDENCE already defines. This function makes no I/O call itself (the
# candidate-selection and cooldown bookkeeping in dissent.py are pure
# Python), so it adds no response-path latency; the only LLM call involved
# is the single existing schedule-agent generation this context gets
# concatenated into (see call site below), matching how _build_goal_
# alignment_context/_build_preference_patterns_context already work.
def _build_dissent_context(
    patterns: list[dict[str, Any]] | None,
    latest_user_text: str,
    thread_id: str | None,
    boldness_adjustment: float,
) -> str | None:
    candidate = select_dissent_candidate(patterns, latest_user_text)
    if not candidate:
        return None
    statement = str(candidate.get("pattern_statement") or "").strip()
    if not statement:
        return None

    record_pending_dissent(
        thread_id, pattern_key=candidate["pattern_key"], pattern_statement=statement
    )

    # dissent.select_dissent_candidate() already guarantees evidence_count
    # above the 傾向層 threshold, so the natural phrasing tier is always
    # 傾向層 (persona.md 5章). boldness_adjustment can only pull this
    # *more* cautious (toward 仮説層 phrasing) when recent reactions have
    # been pushback-dominant — it never pushes phrasing bolder than
    # persona.md's own ceiling (判断根拠、レポート参照: 異論は常により
    # 慎重な方向にのみ調整可能という非対称設計)。
    caution_note = (
        "ただし、海星さんが以前この種の指摘に反発する傾向が見られたため、今回は"
        "特に慎重に、仮説層(「もしかしたら〜かもしれません」)の言い回しに留めて"
        "ください。"
        if boldness_adjustment < _BOLDNESS_PUSHBACK_THRESHOLD
        else ""
    )

    lines = [
        "[判断傾向との食い違いについて(参考情報)]",
        "直前の発言が、過去の判断傾向と食い違っている可能性があります。persona.md "
        "9章(制止する時のルール)・5章(確信度の伝え方)に厳密に従い、「それは以前"
        "の傾向と少し違うかもしれませんね」のような、控えめな確認の形でのみ触れて"
        "よいものです。「それは間違っています」のような断定的な否定は絶対にしない"
        "でください。会話の流れに合わない場合は、無理に触れる必要はありません。"
        + caution_note,
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
# context() above already receives from the BA3 memory snapshot rather than
# issuing a second, deeper topic_tracker.get_recent_topics()
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


def _snapshot_context_parts(
    snapshot: dict[str, Any] | None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any] | None,
    dict[str, Any] | None,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    snapshot = snapshot or {}
    topic_state = snapshot.get("topic_state") if isinstance(snapshot.get("topic_state"), dict) else {}
    goal_alignment_flags = snapshot.get("goal_alignment_flags") if isinstance(snapshot.get("goal_alignment_flags"), list) else []
    goal_alignment_flags = [
        flag for flag in goal_alignment_flags
        if not (isinstance(flag, dict) and flag.get("id") in _recently_surfaced_goal_flag_ids)
    ]
    return (
        snapshot.get("preference_patterns") if isinstance(snapshot.get("preference_patterns"), list) else [],
        topic_state.get("current") if isinstance(topic_state.get("current"), dict) else None,
        topic_state.get("previous") if isinstance(topic_state.get("previous"), dict) else None,
        goal_alignment_flags,
        snapshot.get("entities") if isinstance(snapshot.get("entities"), list) else [],
        snapshot.get("relations") if isinstance(snapshot.get("relations"), list) else [],
    )


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


# Temporal Layer Step 2 (docs/sigmaris/temporal_layer_report.md): "already
# mentioned, don't repeat it" only applies to the scheduler's self-initiated
# morning/evening/weekly briefings (proactive/actions.py), never to ordinary
# user-typed chat — a passive answer must keep working regardless of
# last_mentioned_at (requirement 2), so this whole mechanism is gated on the
# caller_agent_id proactive/actions.py's _run_action() always sets, not on
# any new parameter threaded through run_orchestrator_chat's public signature.
#
# Phase S-6(docs/sigmaris/phase_s_report.md): proactive/actions.pyの3関数
# (旧morning_briefing/evening_checkin/weekly_review)は機能自体を完全廃止
# した。この結果、"proactive-scheduler:"で始まるcaller_agent_idを実際に
# セットする呼び出し元は、コードベース上に一つも存在しなくなった——
# つまり_is_proactive_call()は今後常にFalseを返し、この関数・
# _fact_items_excluding_mentioned_events()は事実上到達不能になっている。
# 実害は無い(通常のユーザーチャットの経路には一切影響しない)ため削除は
# 見送ったが、将来Executive Gate経由の別の自発的発話機構が
# "proactive-scheduler:"プレフィックスを再びセットするようになれば、
# この仕組みは自動的に復活する。
_PROACTIVE_CALLER_PREFIX = "proactive-scheduler:"


def _is_proactive_call(caller_agent_id: str) -> bool:
    return caller_agent_id.startswith(_PROACTIVE_CALLER_PREFIX)


def _fact_items_excluding_mentioned_events(fact_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Proactive-briefing path only: drops event-kind facts Sigmaris has
    already spontaneously mentioned (last_mentioned_at set), so they stop
    competing for build_facts_context()'s top-5 ambient-context slots and a
    still-unmentioned event (or a state/trait fact) can surface instead.
    State/trait/unclassified facts are never filtered — only events carry
    the "don't repeat what I already said" semantics this task addresses."""
    return [
        item
        for item in fact_items
        if not (item.get("memory_kind") == "event" and item.get("last_mentioned_at"))
    ]


async def _mark_events_mentioned_bg(*, jwt: str, event_ids: list[str]) -> None:
    """Fire-and-forget (matches _extract_facts_bg/_cognitive_layer_bg's
    pattern below): records that the events actually surfaced in this
    proactive turn's top-5 facts_ctx were just spontaneously mentioned, so
    the *next* briefing skips them. A failure here only means one future
    briefing might repeat an event once more — never a data-loss risk — so
    it's logged and swallowed rather than propagated."""
    try:
        await mark_facts_mentioned(jwt, event_ids)
    except Exception:
        logger.exception("orchestrator: failed to mark events as mentioned event_ids=%s", event_ids)


# Temporal Layer Step 3 (docs/sigmaris/temporal_layer_report.md): "elapsed
# days" is only worth mentioning at a round number, per the task's own
# examples (100日, 365日) — every multiple of 100 or 365 days.
_RELATIONSHIP_MILESTONE_INTERVALS = (100, 365)


def _is_relationship_milestone(days_elapsed: int) -> bool:
    return days_elapsed > 0 and any(
        days_elapsed % interval == 0 for interval in _RELATIONSHIP_MILESTONE_INTERVALS
    )


def _build_relationship_duration_context(origin_date_iso: str | None) -> str | None:
    """Elapsed-days-awareness context (Temporal Layer Step 3). Injected
    every turn (not just on milestone days) so the LLM can also surface it
    when "a natural moment in conversation" arises, per the task's own
    requirement — a Python-side gate can only recognize the deterministic
    milestone case, not "the conversation flow happened to lead here", so
    the non-milestone branch instead carries an explicit, strongly-worded
    restraint instruction rather than being omitted outright. See
    docs/sigmaris/temporal_layer_report.md for why this split (Python
    decides milestone-or-not deterministically; the LLM decides whether a
    non-milestone moment is "natural" per persona.md) was chosen over
    either extreme (always silent unless milestone, or always free to
    mention).
    """
    if not origin_date_iso:
        return None
    try:
        origin_dt = datetime.fromisoformat(str(origin_date_iso).replace("Z", "+00:00"))
    except ValueError:
        return None

    tz = ZoneInfo("Asia/Tokyo")
    days_elapsed = (datetime.now(tz).date() - origin_dt.astimezone(tz).date()).days
    if days_elapsed <= 0:
        return None

    if _is_relationship_milestone(days_elapsed):
        return (
            f"[関係の積み重ね] 本日で、海星さんとシグマリスの最初の会話から{days_elapsed}日目という節目です。"
            "話の流れが自然であれば触れてよいですが、無理に持ち出す必要はありません。"
        )
    return (
        f"[関係の積み重ね] 海星さんとシグマリスの最初の会話から{days_elapsed}日目です。"
        "節目の日ではないため、本当に自然な文脈でない限りこの情報を自分から持ち出さないでください。"
        "毎回の会話で機械的に言及しないこと。"
    )


def _build_diary_events_context(date_from_iso: str, events: list[dict[str, Any]]) -> str:
    """Temporal Layer Step 3's diary-style date-range context ("7月3日に何
    してた?"). events is already created_at-ascending from
    get_events_in_date_range()'s ORDER BY, so this just formats it."""
    try:
        day_jst = datetime.fromisoformat(str(date_from_iso).replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Tokyo"))
        day_label = f"{day_jst.year}年{day_jst.month}月{day_jst.day}日"
    except ValueError:
        day_label = "指定日"

    if not events:
        return (
            f"[{day_label}の記憶] この日に記録されたevent種別の記憶は見つかりませんでした。"
            "「特に記録がない」旨を素直に伝えてよい。"
        )

    lines = [f"[{day_label}の記憶（時系列）]"]
    for item in events:
        time_label = ""
        created_at = item.get("created_at")
        if created_at:
            try:
                dt_jst = datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Tokyo"))
                time_label = f"{dt_jst.strftime('%H:%M')} "
            except ValueError:
                pass
        cat = item.get("category") or ""
        key = item.get("key") or ""
        val = (item.get("value") or "")[:200]
        lines.append(f"- {time_label}{cat}/{key}: {val}")
    return "\n".join(lines)


# Sigmaris Live(docs/sigmaris/sigmaris_live_report.md、他の処理への拡大):
# memory_search_finished イベントのペイロード(Live-1、2.2節で設計済み)を
# 組み立てるために、_build_memory_context() が既に内部で計算している値
# (検索件数・B7のクエリ分解有無・B11の確信度層・日記検索の発火有無)を、
# 呼び出し元へ持ち帰るためだけの、副作用の無いデータクラス。新しい計測
# ロジックは一切追加していない——いずれも、この関数がこれまで内部でしか
# 使っていなかった、既存の中間結果をそのまま外へ出しているだけである。
@dataclass(frozen=True)
class MemorySearchSummary:
    result_count: int = 0
    was_decomposed: bool = False
    confidence_tier: str | None = None
    diary_search_triggered: bool = False
    # Sigmaris Live「詳細表示、+機密情報のマスキング」タスク: 詳細表示用の、
    # マスキング済みプレビュー(live_detail_masking.py参照)。常にdictを
    # 持つ(該当が無い場合はitems=[])——呼び出し元は、items が空でない
    # 場合のみ、live_event_details.pyへ永続化する(不要な書き込みを
    # 避けるため)。
    masked_detail: dict[str, Any] = field(default_factory=lambda: {"items": [], "any_masked": False})


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
) -> tuple[str | None, MemorySearchSummary]:
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
    result_count = 0
    was_decomposed = False
    confidence_tier: str | None = None
    diary_search_triggered = False
    memory_detail_items: list[dict[str, Any]] = []
    memory_detail_any_masked = False
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
            result_count = len(relevant)
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
            confidence_tier = tier
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
            # Sigmaris Live「詳細表示、+機密情報のマスキング」タスク:
            # 記憶の生の値(value)は、そのままではLive詳細表示に一切
            # 使わない——build_masked_memory_preview()(live_detail_
            # masking.py)で、地名・氏名・日付等をマスキングし、かつ
            # 160文字に切り詰めた「プレビュー」のみを、呼び出し元
            # (run_orchestrator_chat*())経由でsigmaris_live_event_details
            # へ永続化する。category・confidence・similarityは、既存の
            # 要約イベント(memory_search_finished)と同じ、構造的な情報
            # としてそのまま含める。検索クエリ自体(=ユーザーの発言)は、
            # Live-1、4.1節の「ユーザーの発言内容そのものは含めない」
            # という既存方針をそのまま踏襲し、詳細表示にも一切含めない
            # (判断根拠、報告書に詳述)。
            for _item in compressed_relevant:
                _preview, _item_masked = build_masked_memory_preview(str(_item.get("value") or ""))
                memory_detail_items.append(
                    {
                        "category": _item.get("category") or "",
                        "value_preview": _preview,
                        "confidence": _item.get("confidence"),
                        "similarity": _item.get("similarity"),
                    }
                )
                if _item_masked:
                    memory_detail_any_masked = True
            relevant_context = _build_relevant_memories_context(compressed_relevant)
            guidance = confidence_guidance_note(tier)
            if guidance:
                relevant_context = f"{relevant_context}\n{guidance}" if relevant_context else guidance
        except Exception:
            logger.exception("orchestrator: relevant memory search failed")

    # Temporal Layer Step 3: diary-style date questions ("7月3日に何してた?")
    # — a sibling of the B7/B1 relevant_context above, not a replacement.
    # extract_diary_date_range() only returns non-None for messages matching
    # both a resolvable date and an explicit diary trigger phrase (see
    # temporal_parsing.py), so this is a no-op for the overwhelming majority
    # of turns. Runs unconditionally alongside relevant_context rather than
    # branching instead of it, since a genuine diary question could still
    # also have loosely-related B1 hits worth keeping.
    diary_context = None
    if latest_user_text:
        date_range = extract_diary_date_range(latest_user_text, now=datetime.now(UTC))
        if date_range:
            diary_search_triggered = True
            try:
                date_from, date_to = date_range
                events = await get_events_in_date_range(jwt, date_from=date_from, date_to=date_to)
                diary_context = _build_diary_events_context(date_from, events)
            except Exception:
                logger.exception("orchestrator: diary date-range search failed")

    parts = [part for part in (profile_context, diary_context, relevant_context) if part]
    summary = MemorySearchSummary(
        result_count=result_count,
        was_decomposed=was_decomposed,
        confidence_tier=confidence_tier,
        diary_search_triggered=diary_search_triggered,
        masked_detail={"items": memory_detail_items, "any_masked": memory_detail_any_masked},
    )
    return ("\n\n".join(parts) if parts else None), summary


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


def _format_message_timestamp_prefix(created_at: Any) -> str:
    """JST timestamp prefix for one chat_messages row, in the same spirit
    as Step 2's event date hints (user_fact_data.py's
    _format_event_time_hint) — a raw anchor timestamp, not a pre-computed
    relative phrase, since the model already receives the current time
    separately (chat_prompts.py's time_instruction) and doing the
    subtraction here would duplicate that logic in two places."""
    if not created_at:
        return ""
    try:
        dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return ""
    jst = dt.astimezone(ZoneInfo("Asia/Tokyo"))
    return f"[{jst.strftime('%Y-%m-%d %H:%M')} JST] "


def _window_rows_to_messages(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Convert chat_messages rows (parts-based) into the simple role/content
    shape the orchestrator and schedule-agent already use.

    Each row's created_at is prefixed onto its content as a compact JST
    timestamp (see docs/sigmaris/temporal_layer_report.md). Without this,
    every turn in this cross-thread window reached the model as a flat,
    undated {role, content} pair, so it had no way to tell a turn from
    moments ago apart from one several days old — the direct cause of a
    reported "さっき"/"この前" mis-dating bug. Deliberately raw
    (unconverted) timestamps: the model computes the natural relative
    expression itself, per persona.md's time-expression rules, which this
    fix also extended to cover conversation history (previously scoped to
    memory_kind='event' facts only).

    The just-typed latest turn is appended separately by this function's
    only caller (_prepare_session_messages, via _latest_user_message) and
    is deliberately left unprefixed — it's implicitly "now", which
    time_instruction (chat_prompts.py) already tells the model, so dating
    it here would be redundant.
    """
    result: list[dict[str, str]] = []
    for row in rows:
        role = row.get("role")
        if role not in ("user", "assistant"):
            continue
        content = _extract_text_from_parts(row.get("parts"))
        if not content:
            continue
        prefix = _format_message_timestamp_prefix(row.get("created_at"))
        result.append({"role": role, "content": f"{prefix}{content}"})
    return result


def _latest_user_message(messages: list[dict[str, str]]) -> dict[str, str] | None:
    for message in reversed(messages):
        if message.get("role") == "user" and str(message.get("content") or "").strip():
            return {"role": "user", "content": str(message["content"])}
    return None


def _to_storable_new_user_message(
    latest_user: dict[str, str] | None, *, turn_started_at: str
) -> dict[str, Any] | None:
    """Converts _latest_user_message()'s {role, content} shape into the
    {role, parts, metadata}-ish shape chat_messages storage expects (see
    schedule_agent_client.py's new_user_message payload field and
    docs/sigmaris/phase_ba4_report.md). None in, None out — chat.py's
    persistence falls back to its pre-fix behavior when there's no new
    turn to scope persistence around (e.g. a cold-start call with no user
    message at all).

    turn_started_at (message-order-reversal fix, docs/sigmaris/
    phase_ba4_report.md) is stamped as this message's created_at so
    chat.py's chronological merge can place this turn by when it was
    actually *sent* (captured at the very top of run_orchestrator_chat[_
    stream](), before any context-building or LLM latency), not by
    whenever this turn's background generation happens to finish writing —
    see _merge_messages_chronologically()'s docstring in chat.py."""
    if latest_user is None:
        return None
    return {
        "role": "user",
        "parts": [{"type": "text", "text": latest_user["content"]}],
        "created_at": turn_started_at,
    }


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
            user_id=user_id,
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
    user_id: str,
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
    six calls run concurrently since they're independent. jwt/user_id are
    additionally passed to detect_and_record_decision() so it can search for
    turn-relevant facts (related_fact_keys candidates) instead of a fixed
    global-importance-ranked list, see docs/sigmaris/bug_inventory.md 9
    section for why. jwt is also separately
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
                jwt=jwt,
                user_id=user_id,
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
            reflect_dissent_reaction(
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
        # of the six calls above must not leave stale snapshot/threshold-
        # adjustment values cached for the rest of
        # _CACHE_TTL) — same finally-based invalidation approach
        # _extract_facts_bg above uses for the facts cache.
        _cache_pop_prefix("memory_snapshot:")
        _cache.pop("abstention_threshold_adjustment", None)
        _cache.pop("dissent_boldness_adjustment", None)


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
    # Message-order-reversal fix (docs/sigmaris/phase_ba4_report.md):
    # captured here, before any context-building/LLM work, so it reflects
    # when this turn actually arrived rather than when its (possibly slow,
    # possibly backgrounded) generation happens to finish.
    turn_started_at = datetime.now(UTC).isoformat()
    invocation_id = str(uuid.uuid4())

    persona = load_persona()
    agent = get_schedule_agent()

    # Auth + stable context in one parallel gather, then user-scoped facts
    # and the BA3 memory snapshot after user_id is known.
    user, fact_profile, self_model, threshold_adjustment, dissent_boldness_adjustment, active_trends, session = await asyncio.gather(
        _timed(get_current_user(jwt), timeout=8.0),
        _cached_user_profile(jwt),
        _cached_self_model(),
        _cached_threshold_adjustment(),
        _cached_dissent_boldness_adjustment(),
        _cached_active_trends(jwt),
        _prepare_session_messages(jwt=jwt, thread_id=thread_id, messages=messages),
        return_exceptions=False,
    )
    if not user:
        raise RuntimeError("Failed to authenticate user (timeout or error).")
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise RuntimeError("Authenticated Supabase user did not include an id.")
    fact_items, memory_snapshot = await asyncio.gather(
        _cached_fact_items(jwt, user_id),
        _cached_memory_snapshot(user_id),
    )
    effective_thread_id, session_messages, persist_thread = session
    (
        preference_patterns,
        current_topic,
        previous_topic,
        goal_alignment_flags,
        entities,
        relations,
    ) = _snapshot_context_parts(memory_snapshot)

    reason = "User requested schedule assistance through the Sigmaris orchestrator."
    caller_agent_id = settings.schedule_agent_id
    if request_context and isinstance(request_context, dict):
        if isinstance(request_context.get("reason"), str):
            supplied_reason = request_context["reason"].strip()
            if supplied_reason:
                reason = supplied_reason[:500]
        if isinstance(request_context.get("caller_agent_id"), str):
            caller_agent_id = request_context["caller_agent_id"][:80]

    # Temporal Layer Step 2: see _is_proactive_call's docstring above.
    is_proactive = _is_proactive_call(caller_agent_id)
    memory_context_fact_items = (
        _fact_items_excluding_mentioned_events(fact_items) if is_proactive else fact_items
    )

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
    #
    # fact_items= below is memory_context_fact_items, not fact_items, so a
    # proactive briefing's top-5 ambient facts_ctx selection excludes
    # already-mentioned events (Temporal Layer Step 2) — the B1 relevant_
    # context built further inside this same function is untouched by that
    # filtering (search_with_decomposition() below never sees it).
    #
    # Sigmaris Live(他の処理への拡大): classify_chat_intent()と全く同じ
    # fire-and-forgetパターン(emit_live_event()自体が内部で例外を握り
    # つぶすため、呼び出し元でtry/exceptを重ねる必要はない、Live-2で
    # 確立済みの規約をそのまま踏襲)。記憶検索(B1)は一括で結果が確定する
    # バッチ処理であるため(Live-1、5.2節で確認済み)、段階的な演出は
    # 一切行わず、started→(実際の所要時間)→finishedの二値のみを送る。
    _live_memory_search_started_at = time.perf_counter()
    emit_live_event("memory_search_started", invocation_id)
    profile_context, memory_search_summary = await _build_memory_context(
        jwt=jwt,
        user_id=user_id,
        messages=messages,
        fact_profile=fact_profile,
        fact_items=memory_context_fact_items,
        active_trends=active_trends,
        recent_topic_labels=_topic_labels_for_hint(current_topic, previous_topic),
        thread_id=effective_thread_id,
        threshold_adjustment=threshold_adjustment,
        entities=entities,
        relations=relations,
    )
    emit_live_event(
        "memory_search_finished",
        invocation_id,
        result_count=memory_search_summary.result_count,
        was_decomposed=memory_search_summary.was_decomposed,
        confidence_tier=memory_search_summary.confidence_tier,
        diary_search_triggered=memory_search_summary.diary_search_triggered,
        elapsed_ms=int((time.perf_counter() - _live_memory_search_started_at) * 1000),
    )
    # Sigmaris Live「詳細表示、+機密情報のマスキング」タスク: マスキング
    # 済みの詳細(0件の場合は永続化自体をスキップし、不要なDB書き込みを
    # 避ける)を、fire-and-forgetで永続化する。emit_live_event()と同じく
    # 呼び出し元をブロックしない(persist_live_event_detail_bg()内部で
    # asyncio.create_task()するのみ)。
    if memory_search_summary.masked_detail["items"]:
        persist_live_event_detail_bg(
            jwt=jwt,
            user_id=user_id,
            event_type="memory_search_finished",
            detail_key=invocation_id,
            masked_detail=memory_search_summary.masked_detail,
        )

    call_name = extract_call_name(fact_profile) or _user_display_name(user)
    self_model_context = _build_self_model_context(self_model)
    preference_patterns_context = _build_preference_patterns_context(preference_patterns)
    # Phase S-3: appended onto the existing preference_patterns_context
    # channel rather than threaded through as a new schedule_agent_client
    # parameter — see _build_dissent_context's module comment. Reuses the
    # same "concatenate a second context block onto an existing string"
    # splicing already used elsewhere in this function (e.g. trends_ctx
    # onto profile_context).
    dissent_context = _build_dissent_context(
        preference_patterns, _latest_user_content(messages), effective_thread_id, dissent_boldness_adjustment
    )
    if dissent_context and preference_patterns_context:
        preference_patterns_context = preference_patterns_context + "\n\n" + dissent_context
    elif dissent_context:
        preference_patterns_context = dissent_context
    topic_context = _build_topic_context(current_topic, previous_topic)
    goal_alignment_context = _build_goal_alignment_context(goal_alignment_flags)
    persona_context = _build_unified_persona_context(persona, call_name)
    # Temporal Layer Step 3: elapsed-days awareness. Computed every turn (not
    # gated on is_proactive) since a "natural moment in conversation" can
    # arise in ordinary chat, not just proactive briefings.
    relationship_duration_context = _build_relationship_duration_context(
        await _cached_relationship_origin_date(jwt)
    )
    # Self-3: selective injection — see _maybe_build_capability_context's
    # docstring. None on most turns (no DB access at all in that case).
    capability_context = await _maybe_build_capability_context(messages)
    # Context-fabrication / message-order fix (docs/sigmaris/
    # phase_ba4_report.md): messages here is this call's own caller-
    # supplied turn, not session_messages' cross-thread window — exactly
    # the "genuinely new" content chat.py needs to scope persistence to
    # this thread's own history instead of overwriting it with the window.
    new_user_message = _to_storable_new_user_message(
        _latest_user_message(messages), turn_started_at=turn_started_at
    )

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
            persona_context=persona_context,
            relationship_duration_context=relationship_duration_context,
            capability_context=capability_context,
            persist_thread=persist_thread,
            new_user_message=new_user_message,
        )
        response_text, guard_violations = _finalize_unified_response(text=schedule_result.text)
        used_fallback = False
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

    # Phase BA1: surface any inquiry question generated in the background
    # during a *previous* turn (Phase B3's get_inquiry_question used to be
    # awaited synchronously right here, with a 2s timeout — see
    # docs/sigmaris/phase_ba1_report.md for why that was moved off the
    # response path). This is an in-process dict pop, not I/O, so it adds
    # no latency of its own.
    pending_inquiry = _maybe_take_pending_inquiry(effective_thread_id)
    if pending_inquiry:
        response_text = response_text + "\n\n" + pending_inquiry

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

    # Fire-and-forget (Phase BA1): generate this turn's candidate inquiry
    # question, if any, for a *future* turn to surface — see
    # active_inquiry.generate_and_stash_inquiry_question()'s docstring.
    _maybe_stash_future_inquiry(
        jwt=jwt,
        recent_messages=full_messages,
        thread_id=effective_thread_id,
        invocation_id=invocation_id,
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
            user_id=user_id,
        ),
        name=f"cognitive_layer:{invocation_id}",
    )

    # Fire-and-forget (Temporal Layer Step 2): mark whichever event facts
    # actually made it into this proactive turn's top-5 facts_ctx as just
    # spontaneously mentioned, so the next briefing doesn't repeat them.
    # Recomputes the same top-5 selection build_facts_context() made inside
    # _build_memory_context() above (select_top_facts is the shared helper
    # both call) rather than threading the selection back out of that
    # function, since it's a cheap in-process sort over an already-fetched,
    # single-tenant-sized list.
    if is_proactive:
        surfaced_event_ids = [
            item["id"]
            for item in select_top_facts(memory_context_fact_items, top_n=5)
            if item.get("memory_kind") == "event" and item.get("id")
        ]
        if surfaced_event_ids:
            asyncio.create_task(
                _mark_events_mentioned_bg(jwt=jwt, event_ids=surfaced_event_ids),
                name=f"mark_events_mentioned:{invocation_id}",
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
    # Message-order-reversal fix (docs/sigmaris/phase_ba4_report.md): see
    # run_orchestrator_chat's identical block for the full rationale.
    turn_started_at = datetime.now(UTC).isoformat()
    invocation_id = str(uuid.uuid4())

    persona = load_persona()
    agent = get_schedule_agent()

    # Auth + stable context in one parallel gather, then user-scoped facts
    # and the BA3 memory snapshot after user_id is known.
    user, fact_profile, self_model, threshold_adjustment, dissent_boldness_adjustment, active_trends, session = await asyncio.gather(
        _timed(get_current_user(jwt), timeout=8.0),
        _cached_user_profile(jwt),
        _cached_self_model(),
        _cached_threshold_adjustment(),
        _cached_dissent_boldness_adjustment(),
        _cached_active_trends(jwt),
        _prepare_session_messages(jwt=jwt, thread_id=thread_id, messages=messages),
        return_exceptions=False,
    )
    if not user:
        raise RuntimeError("Failed to authenticate user (timeout or error).")
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise RuntimeError("Authenticated Supabase user did not include an id.")
    fact_items, memory_snapshot = await asyncio.gather(
        _cached_fact_items(jwt, user_id),
        _cached_memory_snapshot(user_id),
    )
    effective_thread_id, session_messages, persist_thread = session
    (
        preference_patterns,
        current_topic,
        previous_topic,
        goal_alignment_flags,
        entities,
        relations,
    ) = _snapshot_context_parts(memory_snapshot)

    reason = "User requested schedule assistance through the Sigmaris orchestrator."
    caller_agent_id = settings.schedule_agent_id
    if request_context and isinstance(request_context, dict):
        if isinstance(request_context.get("reason"), str):
            supplied_reason = request_context["reason"].strip()
            if supplied_reason:
                reason = supplied_reason[:500]
        if isinstance(request_context.get("caller_agent_id"), str):
            caller_agent_id = request_context["caller_agent_id"][:80]

    # Temporal Layer Step 2: see _is_proactive_call's docstring above.
    is_proactive = _is_proactive_call(caller_agent_id)
    memory_context_fact_items = (
        _fact_items_excluding_mentioned_events(fact_items) if is_proactive else fact_items
    )

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
    # built inside _build_memory_context() itself, not here. fact_items=
    # below is memory_context_fact_items for the same Temporal Layer Step 2
    # reason documented on run_orchestrator_chat's identical call.
    #
    # Sigmaris Live: see run_orchestrator_chat's identical block for the
    # full rationale.
    _live_memory_search_started_at = time.perf_counter()
    emit_live_event("memory_search_started", invocation_id)
    profile_context, memory_search_summary = await _build_memory_context(
        jwt=jwt,
        user_id=user_id,
        messages=messages,
        fact_profile=fact_profile,
        fact_items=memory_context_fact_items,
        active_trends=active_trends,
        recent_topic_labels=_topic_labels_for_hint(current_topic, previous_topic),
        thread_id=effective_thread_id,
        threshold_adjustment=threshold_adjustment,
        entities=entities,
        relations=relations,
    )
    emit_live_event(
        "memory_search_finished",
        invocation_id,
        result_count=memory_search_summary.result_count,
        was_decomposed=memory_search_summary.was_decomposed,
        confidence_tier=memory_search_summary.confidence_tier,
        diary_search_triggered=memory_search_summary.diary_search_triggered,
        elapsed_ms=int((time.perf_counter() - _live_memory_search_started_at) * 1000),
    )
    # Sigmaris Live「詳細表示、+機密情報のマスキング」タスク: see
    # run_orchestrator_chat's identical block for the full rationale.
    if memory_search_summary.masked_detail["items"]:
        persist_live_event_detail_bg(
            jwt=jwt,
            user_id=user_id,
            event_type="memory_search_finished",
            detail_key=invocation_id,
            masked_detail=memory_search_summary.masked_detail,
        )

    call_name = extract_call_name(fact_profile) or _user_display_name(user)
    self_model_context = _build_self_model_context(self_model)
    preference_patterns_context = _build_preference_patterns_context(preference_patterns)
    # Phase S-3: appended onto the existing preference_patterns_context
    # channel rather than threaded through as a new schedule_agent_client
    # parameter — see _build_dissent_context's module comment. Reuses the
    # same "concatenate a second context block onto an existing string"
    # splicing already used elsewhere in this function (e.g. trends_ctx
    # onto profile_context).
    dissent_context = _build_dissent_context(
        preference_patterns, _latest_user_content(messages), effective_thread_id, dissent_boldness_adjustment
    )
    if dissent_context and preference_patterns_context:
        preference_patterns_context = preference_patterns_context + "\n\n" + dissent_context
    elif dissent_context:
        preference_patterns_context = dissent_context
    topic_context = _build_topic_context(current_topic, previous_topic)
    goal_alignment_context = _build_goal_alignment_context(goal_alignment_flags)
    persona_context = _build_unified_persona_context(persona, call_name)
    # Temporal Layer Step 3: see run_orchestrator_chat's identical block.
    relationship_duration_context = _build_relationship_duration_context(
        await _cached_relationship_origin_date(jwt)
    )
    # Self-3: see run_orchestrator_chat's identical block.
    capability_context = await _maybe_build_capability_context(messages)
    # Context-fabrication / message-order fix: see run_orchestrator_chat's
    # identical block for the full rationale.
    new_user_message = _to_storable_new_user_message(
        _latest_user_message(messages), turn_started_at=turn_started_at
    )
    schedule_text = ""
    tool_events: list[dict[str, Any]] = []
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
            persona_context=persona_context,
            relationship_duration_context=relationship_duration_context,
            capability_context=capability_context,
            persist_thread=persist_thread,
            new_user_message=new_user_message,
        ):
            if event.tool_event:
                tool_events.append(event.tool_event)
                yield OrchestratorStreamEvent(tool_event=event.tool_event, invocation_id=invocation_id)
            if event.delta:
                schedule_text += event.delta
                delta = replace_forbidden_assistant_names(event.delta)
                response_text += delta
                yield OrchestratorStreamEvent(delta=delta, invocation_id=invocation_id)
            if event.done:
                returned_thread_id = event.thread_id or returned_thread_id
                schedule_message_id = event.message_id

        if not schedule_text.strip():
            raise RuntimeError("Schedule agent stream returned an empty response.")

        response_text = replace_forbidden_assistant_names(schedule_text)
        guard = compare_response_to_tool_outputs(
            tool_events=tool_events,
            response_text=response_text,
        )
        guard_violations = guard.violations
        if not guard.passed:
            logger.warning("unified streamed response tool-fact guard failed: %s", guard.violations)
        used_fallback = False

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

    # Phase BA1: same pending-question surfacing as run_orchestrator_chat
    # above, adapted to yield the appended text as a stream delta rather
    # than just concatenating it — see active_inquiry.py's
    # take_pending_inquiry_question()/generate_and_stash_inquiry_question()
    # docstrings and docs/sigmaris/phase_ba1_report.md.
    pending_inquiry = _maybe_take_pending_inquiry(effective_thread_id)
    if pending_inquiry:
        inquiry_delta = "\n\n" + pending_inquiry
        response_text += inquiry_delta
        yield OrchestratorStreamEvent(delta=inquiry_delta, invocation_id=invocation_id)

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

    # Fire-and-forget (Phase BA1): generate this turn's candidate inquiry
    # question, if any, for a *future* turn to surface — see
    # active_inquiry.generate_and_stash_inquiry_question()'s docstring.
    _maybe_stash_future_inquiry(
        jwt=jwt,
        recent_messages=full_messages,
        thread_id=effective_thread_id,
        invocation_id=invocation_id,
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
            user_id=user_id,
        ),
        name=f"cognitive_layer:{invocation_id}",
    )

    # Fire-and-forget (Temporal Layer Step 2): see run_orchestrator_chat's
    # identical block for the full rationale.
    if is_proactive:
        surfaced_event_ids = [
            item["id"]
            for item in select_top_facts(memory_context_fact_items, top_n=5)
            if item.get("memory_kind") == "event" and item.get("id")
        ]
        if surfaced_event_ids:
            asyncio.create_task(
                _mark_events_mentioned_bg(jwt=jwt, event_ids=surfaced_event_ids),
                name=f"mark_events_mentioned:{invocation_id}",
            )

    yield OrchestratorStreamEvent(
        done=True,
        thread_id=returned_thread_id,
        invocation_id=invocation_id,
        agent_id=agent.agent_id,
        used_fallback=used_fallback,
        guard_violations=guard_violations,
    )


async def run_orchestrator_chat_stream_detached(
    *,
    jwt: str,
    google_access_token: str | None,
    google_refresh_token: str | None,
    messages: list[dict[str, str]],
    thread_id: str | None,
    request_context: dict[str, Any] | None,
) -> AsyncGenerator[OrchestratorStreamEvent, None]:
    """Decouples response generation from the frontend's SSE connection
    (docs/sigmaris/phase_ba4_report.md, "フロントエンド切断時の応答継続").

    Investigation found that run_orchestrator_chat_stream() above is itself
    the async generator directly driven by orchestrator.py's StreamingResponse
    — and it in turn drives a *second*, nested HTTP streaming call
    (schedule_agent_client.py's httpx call to /api/agent/chat/stream, which
    wraps chat.py's own OpenAI streaming call). When the frontend
    disconnects, Starlette cancels the outermost generator; that
    cancellation (GeneratorExit) propagates straight through every `async
    for` in this chain, aborting the still-in-flight OpenAI generation
    itself before it finishes. Because chat_messages persistence
    (chat.py::_persist_chat_messages_safely) and this module's own
    fire-and-forget scheduling (_extract_facts_bg / _cognitive_layer_bg /
    _mark_events_mentioned_bg, all below the `async for` loop in
    run_orchestrator_chat_stream) only run *after* generation completes,
    an early disconnect meant the turn was silently lost: never saved,
    never fact-extracted, never decision-detected — matching 海星さん's
    report of losing context after closing the app mid-response.

    Fix: run the *entire* run_orchestrator_chat_stream() generator inside
    an independent asyncio.Task (_produce below), and have this function —
    the one orchestrator.py's route actually iterates — merely relay
    events from a queue that task populates. A bare asyncio.create_task()
    is not part of the request-handling coroutine's own await chain, so
    Starlette cancelling *that* coroutine (on disconnect) does not cancel
    this task — it keeps running to completion regardless, exactly like
    this module's existing _extract_facts_bg/_cognitive_layer_bg
    fire-and-forget tasks already do. If the frontend is still connected
    when an event arrives, it's forwarded normally; if not, the queue
    simply goes unread and is garbage-collected once the background task
    finishes — the generation, persistence, and fire-and-forget scheduling
    all still complete server-side either way.

    Deliberately scoped to the streaming path only: the non-streaming
    run_orchestrator_chat()/`/api/orchestrator/chat` is a single awaited
    coroutine, not an async generator inside an actively disconnect-
    monitored StreamingResponse — Starlette does not run the same
    per-chunk disconnect watcher against it, so it does not share this
    failure mode in the same way and was left as-is.
    """
    queue: asyncio.Queue[OrchestratorStreamEvent | Exception | None] = asyncio.Queue()

    async def _produce() -> None:
        try:
            async for event in run_orchestrator_chat_stream(
                jwt=jwt,
                google_access_token=google_access_token,
                google_refresh_token=google_refresh_token,
                messages=messages,
                thread_id=thread_id,
                request_context=request_context,
            ):
                await queue.put(event)
        except Exception as error:  # noqa: BLE001
            logger.exception("orchestrator: detached stream generation failed")
            await queue.put(error)
        finally:
            await queue.put(None)

    asyncio.create_task(_produce(), name="orchestrator_stream_detached")

    while True:
        item = await queue.get()
        if item is None:
            return
        if isinstance(item, Exception):
            raise item
        yield item
