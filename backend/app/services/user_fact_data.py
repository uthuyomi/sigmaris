from __future__ import annotations

# 役割: ユーザー事実記憶層の読み書きを提供する。

from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config, rest_rpc, rest_select

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
    "privacy_level,thread_id,invocation_id,adoption_count,source_experience_ids"
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

    active_only=True adds is_deleted=eq.false,is_stale=eq.false filters.
    Requires migration 202606270019_trend_memory to be applied.
    """
    params: dict[str, str] = {"select": FACT_ITEM_SELECT, "order": "category.asc,key.asc"}
    if category:
        params["category"] = f"eq.{category}"
    if active_only:
        params["is_deleted"] = "eq.false"
        params["is_stale"] = "eq.false"
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
) -> dict[str, Any]:
    """Atomically upserts one fact item and appends a history row via RPC.

    thread_id/invocation_id (Phase B4 provenance) and source_experience_ids
    (Phase B2 provenance) are only applied by the RPC when this call creates
    a *new* row — they record where a fact was first generated (and, for
    source_experience_ids, which sigmaris_experience rows it was
    consolidated from), not who last touched it, so passing them on an
    update to an existing (category, key) is harmless (the RPC ignores them
    then).
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
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in items:
        if item.get("is_deleted") or item.get("is_stale"):
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
    top = scored[:top_n]

    if not top:
        return None

    lines = ["[記憶した事実（重要度順）]"]
    for _, item in top:
        cat = item.get("category") or ""
        key = item.get("key") or ""
        val = (item.get("value") or "")[:200]
        conf = float(item.get("confidence") or 1.0)
        lines.append(f"- {cat}/{key}: {val}（確信度{conf:.1f}）")

    return "\n".join(lines)
