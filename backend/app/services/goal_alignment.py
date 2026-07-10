from __future__ import annotations

# Phase B16: long-term goal alignment check.
#
# Deliberately reuses existing memory assets rather than building a new
# goal-tracking system (explicit task constraint, same anti-overengineering
# caution as B6): user_fact_items' category='goals' facts are the sole,
# explicit source of 海星さん's long-term goals (B17 already established
# these carry a fixed importance_score of 1.0 — the highest of any
# category), cross-referenced against sigmaris_decision_log (A3/B4) and
# sigmaris_topic_log (B6) as evidence of what's actually been happening.
# No hierarchy, no progress percentages, no goal graph — a flat weekly
# comparison producing, at most, a handful of short flagged observations.
#
# Weekly batch (Sunday 4:35 — see proactive/scheduler.py — chosen to sit in
# the 15-minute gap between decision_analyze at 4:30 and preference_
# pattern_extract at 4:45, so it doesn't collide with any existing job),
# fire-and-forget, same shape as B2's consolidate_episodic_memory() and
# B14's extract_preference_patterns(): never conclude from a single
# decision (mirrors B14's _MIN_SUPPORTING_DECISIONS), only stores a flag
# when the LLM finds *repeated, verifiable* evidence of drift.
#
# Delivery is a separate concern from detection: the extraction prompt
# below asks for a neutral, factual flag_statement (an observation, not a
# verdict) — the persona.md 9章 ("却下"を言わない、確認・提案の形にする)
# tone instructions are applied at *injection* time in
# orchestrator/service.py's _build_goal_alignment_context(), the same
# division B14 already uses between pattern_statement (factual) and the
# hedging-tier instructions wrapped around it at injection time.

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import settings
from app.services.decision_log import get_recent_decisions
from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_search import search_relevant_memories
from app.services.supabase_rest import _get_client, _require_supabase_config
from app.services.topic_tracker import get_recent_topics
from app.services.user_fact_data import get_fact_items_for_user

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_goal_alignment_flags"

# Same volume/evidence gating philosophy as B14: don't even attempt
# extraction below this many total decisions (nothing to find *repeated*
# drift across), and never persist a flag backed by fewer than 2 distinct,
# verified pieces of evidence.
_MIN_DECISIONS_FOR_ANALYSIS = 3
_MIN_SUPPORTING_EVIDENCE = 2

_RECENT_DECISIONS_LIMIT = 50
_RECENT_TOPICS_LIMIT = 20

# How many existing facts (Phase B1 hybrid search) to show the analysis LLM
# as background context, and how many existing flags to show for
# goal_reference reuse. Same two-part design as knowledge_graph.py (B9)/
# decision_log.py's extract_preference_patterns (B14): B1 only indexes
# user_fact_items, not sigmaris_goal_alignment_flags, so the facts search
# alone doesn't address goal_reference fragmentation — showing the existing
# flags directly (not via search) is what actually does that. See
# docs/sigmaris/bug_inventory.md 11 section.
_RELEVANT_FACTS_SEARCH_LIMIT = 15
_EXISTING_FLAGS_CONTEXT_LIMIT = 50

# How often a stored flag may be offered to the response-generation LLM as
# something it *may* mention — a much longer cooldown than active_inquiry.
# py's 48h (Phase B3) or preference-pattern-style context, since a goal-
# alignment observation is more likely to feel like nagging if repeated.
_SURFACE_COOLDOWN_DAYS = 14

_ANALYZE_SYSTEM = (
    "あなたはシグマリスの長期ゴール整合性チェックシステムです。海星さんの長"
    "期的な目標と、直近の決定・話題を照らし合わせ、明らかで繰り返し見られる"
    "乖離のみを検出します。些細な逸脱や単発の出来事は絶対に検出しないでくだ"
    "さい。必ず有効なJSONのみを返してください。"
)

_ANALYZE_PROMPT = """海星さんの長期的な目標(user_fact_itemsのcategory=goals):
{goals}

## 直近の決定記録({decision_count}件、sigmaris_decision_log)
{decisions}

## 直近の話題の推移({topic_count}件、sigmaris_topic_log)
{topics}

## 参考: 関連度の高い既知の記憶(背景理解に使ってよい)
{relevant_facts_context}

## 既に登録されている乖離フラグ(参考。実質的に同じ目標についての乖離であれば、
新しいgoal_referenceを作らず必ずこの一覧のgoal_referenceをそのまま使うこと)
{existing_flags_context}

---
上記の決定・話題が、長期的な目標と明らかに矛盾している、またはある目標から長期
間離れている(その目標に関連する決定・話題が全く見られない)といった、はっき
りしたケースのみを検出してください。

**重要な制約:**
- 1件の決定・話題だけを根拠に乖離を判定しないこと。同じ乖離を裏付ける決定・話
  題が最低2件以上ないかぎり、その乖離は出力しないこと
- 些細な逸脱、一時的な寄り道、単発の出来事は絶対に検出しないこと
- 根拠が薄い場合は無理に乖離を捏造せず、flagsを空リストにしてよい
- flag_statementは断定的な指摘ではなく、観察された事実を中立的に述べる文にする
  こと(例:「目標『AdFlow AIの収益化』について、直近の決定はUI改善に集中して
  おり、収益化に直接つながる決定は見られない」)。伝え方のトーン調整は別の処理
  で行うため、ここでは中立的な記述のみでよい
- 既に登録されている乖離フラグと実質的に同じ目標についての乖離(表現が違うだけ
  の言い換えを含む)を検出する場合は、絶対に新しいgoal_referenceを作らず、既存
  の一覧にあるgoal_referenceをそのまま使うこと。新しいgoal_referenceを作って
  よいのは、既存のどれとも異なる、本当に新しい乖離の場合だけである
- evidence_refsには、根拠とした決定または話題のid(上記に付与されているものを
  そのまま)を全て列挙すること

以下のJSON形式で出力してください:
{{
  "flags": [
    {{
      "goal_reference": "対象の目標を表す短い識別子(目標のkeyやvalueの要約)",
      "flag_statement": "観察された乖離の中立的な説明",
      "evidence_refs": ["id1", "id2", "..."]
    }}
  ]
}}
根拠が2件未満の乖離は絶対に含めないこと。何も見つからなければ
{{"flags": []}} を返してください。"""


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


async def _upsert_flag(
    *,
    goal_reference: str,
    flag_statement: str,
    evidence_refs: list[str],
    analyzed_decision_count: int,
) -> str | None:
    """Insert a new flag, or merge new evidence into an existing one
    (matched by goal_reference) — same accumulate-across-runs pattern as
    decision_log._upsert_preference_pattern (Phase B14)."""
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    now = datetime.now(UTC).isoformat()

    existing_resp = await client.get(
        f"{base_url}/rest/v1/{_TABLE}",
        headers=_svc_headers(),
        params={"goal_reference": f"eq.{goal_reference}", "select": "id,evidence_refs"},
    )
    existing_resp.raise_for_status()
    existing_rows = existing_resp.json()
    existing = existing_rows[0] if isinstance(existing_rows, list) and existing_rows else None

    if existing:
        prior_refs = existing.get("evidence_refs")
        prior_refs = prior_refs if isinstance(prior_refs, list) else []
        merged_refs = list(dict.fromkeys([*prior_refs, *evidence_refs]))
        payload = {
            "flag_statement": flag_statement,
            "evidence_refs": merged_refs,
            "evidence_count": len(merged_refs),
            "last_confirmed_at": now,
            "last_analyzed_decision_count": analyzed_decision_count,
        }
        resp = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            params={"id": f"eq.{existing['id']}"},
            json=payload,
        )
    else:
        payload = {
            "goal_reference": goal_reference,
            "flag_statement": flag_statement,
            "evidence_refs": evidence_refs,
            "evidence_count": len(evidence_refs),
            "last_confirmed_at": now,
            "last_analyzed_decision_count": analyzed_decision_count,
        }
        resp = await client.post(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            json=payload,
        )

    resp.raise_for_status()
    rows = resp.json()
    return rows[0].get("id") if isinstance(rows, list) and rows else None


async def _build_relevant_facts_context(
    decisions: list[dict[str, Any]], topics: list[dict[str, Any]], *, jwt: str | None, user_id: str
) -> str:
    """B1 hybrid search over user_fact_items, using this batch's decision
    titles + topic labels (concatenated) as the query — same query-strategy
    reasoning as knowledge_graph.py's (B9) analogous fix, which reads the
    same three sources."""
    query = " / ".join(
        [
            *(str(d.get("title")).strip() for d in decisions if isinstance(d.get("title"), str) and d.get("title").strip()),
            *(str(t.get("topic_label")).strip() for t in topics if isinstance(t.get("topic_label"), str) and t.get("topic_label").strip()),
        ]
    )[:2000]
    if not query or not jwt:
        return "（なし）"

    try:
        results = await search_relevant_memories(
            query, user_id, limit=_RELEVANT_FACTS_SEARCH_LIMIT, jwt=jwt
        )
    except Exception:
        logger.debug("goal_alignment: relevant-facts search failed, proceeding without it", exc_info=True)
        return "（なし）"

    lines = [
        f"- {row.get('category')}/{row.get('key')}: {row.get('value')}"
        for row in results
        if isinstance(row.get("category"), str) and isinstance(row.get("key"), str) and row.get("value")
    ]
    return "\n".join(lines) if lines else "（なし）"


async def _get_all_flags_for_context(limit: int = _EXISTING_FLAGS_CONTEXT_LIMIT) -> list[dict[str, Any]]:
    """All stored flags regardless of surface-cooldown status, for
    goal_reference-reuse context — deliberately separate from
    get_active_goal_alignment_flags(), whose cooldown filter exists for a
    different purpose (deciding what's eligible to show 海星さん right now)
    and would wrongly hide an on-cooldown flag's goal_reference from this
    dedup check, defeating the point."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"order": "evidence_count.desc,last_confirmed_at.desc", "limit": str(limit)},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("goal_alignment: failed to _get_all_flags_for_context")
        return []


def _build_existing_flags_context(flags: list[dict[str, Any]]) -> str:
    lines = [
        f"- {f.get('goal_reference')}: {f.get('flag_statement')}"
        for f in flags
        if isinstance(f.get("goal_reference"), str) and f.get("flag_statement")
    ]
    return "\n".join(lines) if lines else "（なし）"


async def extract_goal_alignment_flags(user_id: str, *, jwt: str | None = None) -> dict[str, Any]:
    """Sunday 4:35 AM scheduled: cross-reference category='goals' facts
    against recent decisions/topics, storing only clearly and repeatedly
    evidenced drift. Deliberately conservative — see this module's
    docstring and phase_b16_report.md for the full reasoning.

    jwt is optional (used only for the relevant-facts B1 search); omitting
    it degrades that one context block to "（なし）" without blocking
    extraction.
    """
    result: dict[str, Any] = {
        "goals_found": 0,
        "decisions_analyzed": 0,
        "topics_analyzed": 0,
        "candidates_found": 0,
        "flags_stored": 0,
        "errors": 0,
        "insufficient_data": False,
    }
    try:
        goals = await get_fact_items_for_user(user_id, category="goals", active_only=True)
        result["goals_found"] = len(goals)

        decisions = await get_recent_decisions(limit=_RECENT_DECISIONS_LIMIT)
        result["decisions_analyzed"] = len(decisions)

        topics = await get_recent_topics(limit=_RECENT_TOPICS_LIMIT)
        result["topics_analyzed"] = len(topics)

        if not goals or len(decisions) < _MIN_DECISIONS_FOR_ANALYSIS:
            result["insufficient_data"] = True
            logger.info(
                "goal_alignment: extraction skipped — goals=%d decisions=%d (need >= 1 goal, >= %d decisions)",
                len(goals), len(decisions), _MIN_DECISIONS_FOR_ANALYSIS,
            )
            return result

        decision_ids = {d.get("id") for d in decisions if d.get("id")}
        topic_ids = {t.get("id") for t in topics if t.get("id")}
        evidence_ids = decision_ids | topic_ids

        goal_lines = "\n".join(
            f"- key={g.get('key')} value={g.get('value')}" for g in goals
        )
        decision_lines = "\n".join(
            f"- id={d.get('id')} type={d.get('decision_type')} title={d.get('title')} "
            f"reason={(d.get('reason') or 'N/A')[:150]} outcome={(d.get('outcome') or 'N/A')[:150]}"
            for d in decisions
        )
        topic_lines = "\n".join(
            f"- id={t.get('id')} label={t.get('topic_label')}" for t in topics
        ) or "（なし）"

        relevant_facts_context = await _build_relevant_facts_context(
            decisions, topics, jwt=jwt, user_id=user_id
        )
        existing_flags = await _get_all_flags_for_context()
        existing_flags_context = _build_existing_flags_context(existing_flags)

        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": _ANALYZE_SYSTEM},
                {"role": "user", "content": _ANALYZE_PROMPT.format(
                    goals=goal_lines or "（なし）",
                    decision_count=len(decisions),
                    decisions=decision_lines or "（なし）",
                    topic_count=len(topics),
                    topics=topic_lines,
                    relevant_facts_context=relevant_facts_context,
                    existing_flags_context=existing_flags_context,
                )},
            ],
            temperature=0.2,
            max_tokens=800,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        candidates = parsed.get("flags") if isinstance(parsed, dict) else None
        if not isinstance(candidates, list):
            candidates = []
        result["candidates_found"] = len(candidates)

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            goal_reference = str(candidate.get("goal_reference") or "").strip()
            flag_statement = str(candidate.get("flag_statement") or "").strip()
            if not goal_reference or not flag_statement:
                continue

            raw_refs = candidate.get("evidence_refs")
            # Only trust refs that actually exist among the decisions/
            # topics we sent the LLM — never take an LLM-invented id at
            # face value (same defensive pattern as B7/B14).
            supporting_refs = list(dict.fromkeys(
                ref for ref in (raw_refs if isinstance(raw_refs, list) else [])
                if isinstance(ref, str) and ref in evidence_ids
            ))
            if len(supporting_refs) < _MIN_SUPPORTING_EVIDENCE:
                logger.debug(
                    "goal_alignment: discarding candidate '%s' — only %d verifiable "
                    "supporting refs (need >= %d)",
                    goal_reference, len(supporting_refs), _MIN_SUPPORTING_EVIDENCE,
                )
                continue

            try:
                await _upsert_flag(
                    goal_reference=goal_reference,
                    flag_statement=flag_statement,
                    evidence_refs=supporting_refs,
                    analyzed_decision_count=len(decisions),
                )
                result["flags_stored"] += 1
            except Exception:
                logger.exception("goal_alignment: failed to store flag goal_reference=%s", goal_reference)
                result["errors"] += 1

        logger.info(
            "goal_alignment: extraction done goals=%d decisions=%d topics=%d found=%d stored=%d",
            result["goals_found"], result["decisions_analyzed"], result["topics_analyzed"],
            result["candidates_found"], result["flags_stored"],
        )
        return result
    except Exception:
        logger.exception("goal_alignment: failed to extract_goal_alignment_flags")
        result["errors"] += 1
        return result


async def get_active_goal_alignment_flags(limit: int = 1) -> list[dict[str, Any]]:
    """Return stored flags eligible to be surfaced right now — evidence_
    count already enforced at write time (>=_MIN_SUPPORTING_EVIDENCE), and
    filtered here to exclude anything surfaced within _SURFACE_COOLDOWN_
    DAYS (requirement: don't nag). Ordered most-evidenced first."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        cutoff = (datetime.now(UTC) - timedelta(days=_SURFACE_COOLDOWN_DAYS)).isoformat()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={
                "or": f"(last_surfaced_at.is.null,last_surfaced_at.lt.{cutoff})",
                "order": "evidence_count.desc,last_confirmed_at.desc",
                "limit": str(limit),
            },
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("goal_alignment: failed to get_active_goal_alignment_flags")
        return []


# Phase B16: pending-surface tracking. Not thread-keyed (unlike B3/B15's
# per-thread pending state) since this system is single-tenant — there is
# only ever one active conversation stream, so any subsequent fire-and-
# forget pass (regardless of which thread it's attached to) is a valid
# place to persist "this flag was just offered to the model". Marked
# during response building (_build_goal_alignment_context, response path,
# read-only otherwise) and flushed to the DB from orchestrator's existing
# background cognitive layer — never a synchronous write on the response
# path.
_pending_surfaced_flag_ids: set[str] = set()


def mark_pending_surfaced(flag_id: str | None) -> None:
    if flag_id:
        _pending_surfaced_flag_ids.add(flag_id)


async def _mark_surfaced(flag_id: str) -> None:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.patch(
        f"{base_url}/rest/v1/{_TABLE}",
        headers=_svc_headers(prefer="return=minimal"),
        params={"id": f"eq.{flag_id}"},
        json={"last_surfaced_at": datetime.now(UTC).isoformat()},
    )
    r.raise_for_status()


async def flush_pending_surfaced_flags() -> None:
    """Fire-and-forget: persist last_surfaced_at for any flags marked
    pending during response building, off the response path entirely."""
    if not _pending_surfaced_flag_ids:
        return
    pending_ids = list(_pending_surfaced_flag_ids)
    _pending_surfaced_flag_ids.clear()
    for flag_id in pending_ids:
        try:
            await _mark_surfaced(flag_id)
        except Exception:
            logger.exception("goal_alignment: failed to mark_surfaced flag_id=%s", flag_id)
