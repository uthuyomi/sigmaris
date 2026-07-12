from __future__ import annotations

# 役割: ユーザー事実記憶層の読み書きを提供する。

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config, rest_rpc, rest_select, rest_update

# Category-level importance scores (mirrors DB trigger set_fact_category_defaults).
# Used for Python-side sorting without requiring the DB column to exist.
CATEGORY_IMPORTANCE: dict[str, float] = {
    "goals":         1.0,
    "health":        0.9,
    "profile":       0.8,
    "relationships": 0.8,
    "finance":       0.7,
    "work":          0.7,
    "personality":   0.7,
    "timeline":      0.7,
    "lifestyle":     0.6,
    "preferences":   0.5,
    "preference":    0.5,
    "devices":       0.4,
    "environment":   0.4,
}

_PROFILE_SCALAR_FIELDS = [
    "name", "birthdate", "prefecture", "city", "address_detail",
    "email", "occupation", "income_range",
]
_PROFILE_JSONB_FIELDS = [
    "lifestyle_notes", "devices", "preferences", "goals", "values", "communication_settings",
]

# Phase BA2: every current reader of user_fact_items (get_fact_items,
# get_fact_items_for_user below, plus memory_validator.py's
# get_confirmation_candidates/validate_all_facts) reads only these columns —
# none touch `embedding` (vector(768), never read back into Python; all
# vector similarity happens server-side via the search_fact_memory RPC in
# memory_search.py) or the generated `search_text` column. This mirrors the
# exclusion Phase B5's _DASHBOARD_SELECT below already established, just
# generalized to every general-purpose reader instead of only the
# dashboard. Excluding `embedding` was measured to remove the ~0.6s parse
# overhead docs/sigmaris/incident_response_latency_investigation.md 6.5
# section noted for the ~380-row full active-facts fetch.
FACT_ITEM_SELECT = (
    "id,user_id,category,key,value,confidence,source,notes,expires_at,"
    "created_at,updated_at,is_stale,is_deleted,deleted_at,importance_score,"
    "privacy_level,thread_id,invocation_id,adoption_count,source_experience_ids,"
    "memory_kind,valid_from,superseded_by,last_mentioned_at"
)


async def get_user_profile(jwt: str) -> dict[str, Any] | None:
    """Returns the single user_fact_profile row, or None if it does not exist yet."""
    return await rest_select(jwt, "user_fact_profile", {"select": "*"}, single=True)


async def get_fact_items(
    jwt: str,
    *,
    category: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """Returns user_fact_items, optionally filtered by category.

    active_only=True adds is_deleted=eq.false,is_stale=eq.false,
    superseded_by=is.null filters. Requires migration
    202606270019_trend_memory to be applied.
    """
    params: dict[str, str] = {"select": FACT_ITEM_SELECT, "order": "category.asc,key.asc"}
    if category:
        params["category"] = f"eq.{category}"
    if active_only:
        params["is_deleted"] = "eq.false"
        params["is_stale"] = "eq.false"
        # Temporal layer: a superseded state fact (an old value a newer
        # state fact has replaced, per upsert_fact_item()'s invalidate-
        # never-delete branch) is not "active" in the same sense
        # is_deleted/is_stale already gate on — see
        # docs/sigmaris/temporal_layer_report.md. Rows with memory_kind
        # other than 'state' (or NULL, i.e. every pre-existing row) never
        # get superseded_by set, so this is a no-op for them.
        params["superseded_by"] = "is.null"
    result = await rest_select(jwt, "user_fact_items", params)
    return result if isinstance(result, list) else []


async def get_fact_items_with_embeddings(
    jwt: str,
    *,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """Returns user_fact_items rows *including* the embedding column —
    a deliberate, narrowly-scoped exception to FACT_ITEM_SELECT's exclusion
    of `embedding` (Phase BA2, see that constant's comment). BA2 excluded
    embedding because no general-purpose caller ever read it back into
    Python (all vector search happens server-side via the search_fact_
    memory RPC); Phase C-full-2's SB-3 (memory_duplicate_rate) is the first
    caller that genuinely needs the raw vectors client-side, to compute
    all-pairs cosine similarity across a user's whole fact set at once —
    something the existing RPCs aren't shaped for (they rank one query
    embedding against the corpus, not corpus-against-itself). This is an
    occasional, offline eval-script read, not a per-chat-turn hot path, so
    the transfer/parse cost BA2 was optimizing away is an acceptable
    trade-off here.

    Each row's "embedding" value comes back from PostgREST as either a
    JSON array or (depending on pgvector/PostgREST version) a bracket
    string like "[0.1,0.2,...]" — both are valid JSON, so callers should
    parse it with json.loads() if it's a str. See eval_metrics.py's
    compute_memory_duplicate_rate() for where that parsing happens.
    """
    params: dict[str, str] = {
        "select": f"{FACT_ITEM_SELECT},embedding",
        "order": "category.asc,key.asc",
    }
    if active_only:
        params["is_deleted"] = "eq.false"
        params["is_stale"] = "eq.false"
        # Temporal layer: a superseded state fact (an old value a newer
        # state fact has replaced, per upsert_fact_item()'s invalidate-
        # never-delete branch) is not "active" in the same sense
        # is_deleted/is_stale already gate on — see
        # docs/sigmaris/temporal_layer_report.md. Rows with memory_kind
        # other than 'state' (or NULL, i.e. every pre-existing row) never
        # get superseded_by set, so this is a no-op for them.
        params["superseded_by"] = "is.null"
    result = await rest_select(jwt, "user_fact_items", params)
    return result if isinstance(result, list) else []


async def get_fact_items_for_user(
    user_id: str,
    *,
    category: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """Return fact items for a user with the service role.

    Server-side callers use this after authenticating the caller and resolving
    the concrete user_id. It prevents imported memories from disappearing from
    Sigmaris context when a user JWT cannot see service-role inserted rows.
    """
    base_url, _ = _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")

    params: dict[str, str] = {
        "select": FACT_ITEM_SELECT,
        "user_id": f"eq.{user_id}",
        "order": "category.asc,key.asc",
    }
    if category:
        params["category"] = f"eq.{category}"
    if active_only:
        params["is_deleted"] = "eq.false"
        params["is_stale"] = "eq.false"
        # Temporal layer: a superseded state fact (an old value a newer
        # state fact has replaced, per upsert_fact_item()'s invalidate-
        # never-delete branch) is not "active" in the same sense
        # is_deleted/is_stale already gate on — see
        # docs/sigmaris/temporal_layer_report.md. Rows with memory_kind
        # other than 'state' (or NULL, i.e. every pre-existing row) never
        # get superseded_by set, so this is a no-op for them.
        params["superseded_by"] = "is.null"

    client = await _get_client()
    response = await client.get(
        f"{base_url}/rest/v1/user_fact_items",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        params=params,
    )
    response.raise_for_status()
    result = response.json()
    return result if isinstance(result, list) else []


async def get_fact_items_by_ids(fact_ids: list[str]) -> list[dict[str, Any]]:
    """Return user_fact_items rows for a specific set of ids, service-role
    (same rationale as get_fact_items_for_user: this is Sigmaris's own
    introspection, not a user-initiated request with a JWT in hand).

    Phase R-1 (docs/sigmaris/phase_r_report.md): the dereferencing step
    cycle_trace.py uses to turn an id reference (decision_log.memory_refs,
    sigmaris_goal_alignment_flags.goal_fact_ids, ...) into the actual
    Memory-stage rows it points at. Order is whatever PostgREST returns
    (not meaningful for a fixed id set); callers needing a specific order
    should re-sort client-side.
    """
    ids = [str(fid) for fid in fact_ids if fid]
    if not ids:
        return []
    base_url, _ = _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")

    client = await _get_client()
    response = await client.get(
        f"{base_url}/rest/v1/user_fact_items",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        params={"select": FACT_ITEM_SELECT, "id": f"in.({','.join(ids)})"},
    )
    response.raise_for_status()
    result = response.json()
    return result if isinstance(result, list) else []


# Phase B5: columns needed by the memory freshness/contradiction dashboard.
# Deliberately excludes `embedding` (vector(768), large and irrelevant to a
# human-facing list) and the generated `search_text` column.
_DASHBOARD_SELECT = (
    "id,category,key,value,confidence,importance_score,is_stale,"
    "adoption_count,source,thread_id,invocation_id,source_experience_ids,"
    "created_at,updated_at"
)


async def get_memory_dashboard_items(jwt: str) -> list[dict[str, Any]]:
    """Returns non-deleted user_fact_items for Phase B5's developer dashboard.

    Ordered oldest-updated-first by default (the items most overdue for
    review surface first); the frontend re-sorts/filters client-side from
    this single snapshot rather than round-tripping for each view, since the
    per-user row count is small (single-tenant system).

    Includes is_stale rows on purpose (that's the whole point of the
    dashboard) but excludes is_deleted rows (logically gone, nothing to
    review).
    """
    params = {
        "select": _DASHBOARD_SELECT,
        "is_deleted": "eq.false",
        "order": "updated_at.asc",
    }
    result = await rest_select(jwt, "user_fact_items", params)
    return result if isinstance(result, list) else []


async def upsert_fact_item(
    jwt: str,
    *,
    category: str,
    key: str,
    value: str | None,
    confidence: float = 1.0,
    source: str = "manual",
    reason: str = "",
    notes: str | None = None,
    expires_at: str | None = None,
    thread_id: str | None = None,
    invocation_id: str | None = None,
    source_experience_ids: list[str] | None = None,
    memory_kind: str | None = None,
    valid_from: str | None = None,
) -> dict[str, Any]:
    """Atomically upserts one fact item and appends a history row via RPC.

    thread_id/invocation_id (Phase B4 provenance) and source_experience_ids
    (Phase B2 provenance) are only applied by the RPC when this call creates
    a *new* row — they record where a fact was first generated (and, for
    source_experience_ids, which sigmaris_experience rows it was
    consolidated from), not who last touched it, so passing them on an
    update to an existing (category, key) is harmless (the RPC ignores them
    then).

    memory_kind/valid_from (temporal layer, see
    docs/sigmaris/temporal_layer_report.md): when memory_kind='state' and
    this call's value contradicts an existing active row for the same
    (category, key), the RPC invalidates the old row (superseded_by, never
    deleted) instead of overwriting it in place — every other case
    (event/trait/None, or a 'state' call with no existing row or an
    unchanged value) behaves as a plain upsert-in-place, unchanged from
    before this parameter existed. valid_from is only meaningful for
    memory_kind='state'; the RPC defaults it to "now" if omitted.
    """
    return await rest_rpc(jwt, "upsert_fact_item", {
        "p_category": category,
        "p_key": key,
        "p_value": value,
        "p_confidence": confidence,
        "p_source": source,
        "p_reason": reason,
        "p_notes": notes,
        "p_expires_at": expires_at,
        "p_memory_kind": memory_kind,
        "p_valid_from": valid_from,
        "p_thread_id": thread_id,
        "p_invocation_id": invocation_id,
        "p_source_experience_ids": source_experience_ids,
    })


async def get_null_fields(jwt: str) -> list[dict[str, str]]:
    """Returns profile fields and fact items where value is null — candidates for Sigmaris to fill."""
    profile = await get_user_profile(jwt)
    items = await get_fact_items(jwt)
    missing: list[dict[str, str]] = []

    if profile is None:
        for field in _PROFILE_SCALAR_FIELDS + _PROFILE_JSONB_FIELDS:
            missing.append({"source": "user_fact_profile", "key": field})
    else:
        for field in _PROFILE_SCALAR_FIELDS + _PROFILE_JSONB_FIELDS:
            if profile.get(field) is None:
                missing.append({"source": "user_fact_profile", "key": field})

    for item in items:
        if item.get("value") is None:
            missing.append({
                "source": "user_fact_items",
                "category": item.get("category", ""),
                "key": item.get("key", ""),
                "id": item.get("id", ""),
            })

    return missing


def build_profile_context(profile: dict[str, Any] | None) -> str | None:
    """Formats a compact profile summary for injection into the schedule agent's system prompt."""
    if not profile:
        return None

    lines: list[str] = ["[ユーザーコンテキスト]"]

    name = profile.get("name")
    comm = profile.get("communication_settings")
    nickname = comm.get("nickname") if isinstance(comm, dict) else None
    if name:
        call = f"（呼称: {nickname}）" if nickname else ""
        lines.append(f"氏名: {name}{call}")

    parts = [profile.get("prefecture"), profile.get("city")]
    location = " ".join(p for p in parts if p)
    if location:
        lines.append(f"居住地: {location}")

    if profile.get("occupation"):
        lines.append(f"職業: {profile['occupation']}")

    env_prefs = profile.get("preferences")
    if isinstance(env_prefs, dict) and env_prefs.get("hobbies"):
        hobbies = env_prefs["hobbies"]
        if isinstance(hobbies, list):
            lines.append(f"趣味: {', '.join(hobbies[:5])}")

    goals = profile.get("goals")
    if isinstance(goals, dict):
        short = goals.get("short_term")
        if isinstance(short, list) and short:
            lines.append(f"直近の目標: {', '.join(short[:3])}")

    if isinstance(comm, dict) and comm.get("tone"):
        lines.append(f"コミュニケーション: {comm['tone']}")

    if len(lines) == 1:
        return None
    return "\n".join(lines)


def extract_call_name(profile: dict[str, Any] | None) -> str | None:
    """Returns the user's preferred call name from communication_settings.nickname."""
    if not profile:
        return None
    comm = profile.get("communication_settings")
    if isinstance(comm, dict):
        nickname = comm.get("nickname")
        if isinstance(nickname, str) and nickname.strip():
            return nickname.strip()
    return None


def select_top_facts(
    items: list[dict[str, Any]],
    *,
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Sorts fact items by importance_score × confidence (descending) and
    returns the top N items that have a non-null value. Falls back to
    CATEGORY_IMPORTANCE when the importance_score column does not yet exist
    on the row.

    Split out of build_facts_context() (Temporal Layer Step 2) so the
    orchestrator's proactive-briefing path can determine *which* event facts
    would be surfaced this turn — needed to fire the last_mentioned_at
    update for exactly those facts, without duplicating the selection logic.
    See docs/sigmaris/temporal_layer_report.md.
    """
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in items:
        # superseded_by (temporal layer): an invalidated state fact — the
        # old value a newer, contradicting state fact replaced. Same
        # reasoning as excluding is_deleted/is_stale: this function forms
        # the schedule-agent's injected memory context, and showing a
        # superseded fact here is exactly the "reports old info as current"
        # symptom this feature exists to fix. get_fact_items(active_only=
        # True) already filters this at the query level, but this function
        # takes whatever list it's handed, so it re-checks defensively.
        if item.get("is_deleted") or item.get("is_stale") or item.get("superseded_by"):
            continue
        value = item.get("value")
        if value is None:
            continue
        importance = float(
            item.get("importance_score")
            or CATEGORY_IMPORTANCE.get(item.get("category") or "", 0.5)
        )
        confidence = float(item.get("confidence") or 1.0)
        scored.append((importance * confidence, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_n]]


def _format_event_time_hint(created_at: Any) -> str:
    """Renders an event fact's created_at as a compact JST timestamp, so the
    persona-generation LLM can compute a natural relative-time expression
    itself (persona.md's time-expression rules, Temporal Layer Step 2) —
    this function only supplies the raw anchor date, never a pre-computed
    phrase like "3日前", since the LLM already receives the current time
    separately (chat_prompts.py's time_instruction) and doing the subtraction
    in Python would duplicate that logic in two places."""
    if not created_at:
        return ""
    try:
        dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return ""
    jst = dt.astimezone(ZoneInfo("Asia/Tokyo"))
    return f"（発生日時の目安: {jst.strftime('%Y-%m-%d %H:%M')} JST）"


def build_facts_context(
    items: list[dict[str, Any]],
    *,
    top_n: int = 20,
) -> str | None:
    """Format fact items for injection into the schedule-agent system prompt.

    Sorts items by importance_score × confidence (descending) and includes the
    top N items that have a non-null value. Falls back to CATEGORY_IMPORTANCE
    when the importance_score column does not yet exist on the row.
    """
    top = select_top_facts(items, top_n=top_n)

    if not top:
        return None

    lines = ["[記憶した事実（重要度順）]"]
    for item in top:
        cat = item.get("category") or ""
        key = item.get("key") or ""
        val = (item.get("value") or "")[:200]
        conf = float(item.get("confidence") or 1.0)
        # Temporal Layer Step 2: only event-kind facts get a date hint —
        # state/trait facts are meant to be stated as current fact without a
        # time qualifier (persona.md's time-expression rules), so attaching
        # one here would actively contradict that rule.
        time_hint = _format_event_time_hint(item.get("created_at")) if item.get("memory_kind") == "event" else ""
        lines.append(f"- {cat}/{key}: {val}（確信度{conf:.1f}）{time_hint}")

    return "\n".join(lines)


async def get_events_in_date_range(
    jwt: str,
    *,
    date_from: str,
    date_to: str,
) -> list[dict[str, Any]]:
    """Direct (non-embedding) date-range query for Temporal Layer Step 3's
    diary-style questions ("7月3日に何してた?") — active event-kind facts
    whose created_at falls in [date_from, date_to), oldest first.

    Deliberately bypasses the B1 vector/trigram RPCs (search_fact_memory /
    search_fact_memory_trgm): those rank a fixed-size candidate pool by
    similarity to a query string, which is the wrong tool for "return
    everything recorded on this specific day" — an exhaustive, unranked
    date-window scan is what a diary question actually needs. This is a
    sibling read path on the same table B1 already indexes, not a change to
    B1's own search/ranking logic (search_relevant_memories() and the two
    RPCs are untouched). See docs/sigmaris/temporal_layer_report.md.

    Uses PostgREST's `and=(...)` combinator (see app_event_data.py's
    search_events() for the same pattern) since date_from/date_to are two
    conditions on the *same* created_at column — a plain dict can't express
    two filters under one key.
    """
    params: dict[str, str] = {
        "select": FACT_ITEM_SELECT,
        "memory_kind": "eq.event",
        "is_deleted": "eq.false",
        "is_stale": "eq.false",
        "superseded_by": "is.null",
        "and": f"(created_at.gte.{date_from},created_at.lt.{date_to})",
        "order": "created_at.asc",
    }
    result = await rest_select(jwt, "user_fact_items", params)
    return result if isinstance(result, list) else []


async def mark_facts_mentioned(jwt: str, fact_ids: list[str]) -> None:
    """Records that Sigmaris just spontaneously said these fact_ids out loud
    (Temporal Layer Step 2's last_mentioned_at) — called fire-and-forget from
    the proactive-briefing path only (orchestrator/service.py's is_proactive
    gate), never from ordinary chat, so a passive answer never marks an event
    "already mentioned" and blocks the next legitimate spontaneous mention.
    See docs/sigmaris/temporal_layer_report.md.
    """
    ids = [fact_id for fact_id in fact_ids if fact_id]
    if not ids:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    await rest_update(
        jwt,
        "user_fact_items",
        {"last_mentioned_at": now_iso},
        {"id": f"in.({','.join(ids)})"},
    )
