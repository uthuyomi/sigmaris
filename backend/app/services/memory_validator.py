from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.local_llm import TaskType, get_llm_router
from app.services.supabase_rest import rest_delete, rest_insert, rest_select, rest_update

logger = logging.getLogger(__name__)

# (decay_days, decay_factor) — None means no decay
_DECAY_RULES: dict[str, tuple[int | None, float]] = {
    "profile":       (None, 1.0),
    "lifestyle":     (90,   0.7),
    "health":        (30,   0.5),
    "finance":       (60,   0.6),
    "devices":       (180,  0.8),
    "goals":         (60,   0.7),
    "relationships": (120,  0.7),
    "preferences":   (90,   0.8),
    "environment":   (180,  0.9),
}

# importance_score × confidence below this → logical delete
_FORGET_THRESHOLD = 0.1
# physical delete this many days after is_deleted=true is set
_PHYSICAL_DELETE_DAYS = 30
# LLM contradiction check budget per run (cost control)
_MAX_CONTRADICTION_CHECKS = 5

# Phase B17: importance_score (0.0-1.0) softens confidence decay (Phase 1
# below) — NOT a full exemption (requirement: "重要度に応じて減衰の閾値・
# 速度を調整する形にすること", explicitly not full immunity), and does not
# touch contradiction detection (Phase 2) at all, so a high-importance fact
# that's genuinely contradicted still gets flagged (requirement 3).
#
# At importance=1.0: decay onset is delayed to 2x the base category window,
# and the confidence drop when decay does trigger is halved (severity
# 1-decay_factor cut by 50%). At importance=0.0: unchanged from the
# pre-B17 category-only behavior. Both scale linearly with importance in
# between. Phase 3 (logical deletion) already multiplies importance x
# confidence against _FORGET_THRESHOLD — no change needed there, it was
# already importance-aware.
_IMPORTANCE_DECAY_ONSET_EXTENSION = 1.0
_IMPORTANCE_DECAY_SEVERITY_DAMPENING = 0.5

# Phase B3: active-inquiry confirmation-candidate selection.
#
# 0.5 sits exactly on the boundary memory_extractor.py's own extraction
# prompt already uses to calibrate confidence at creation time (0.4 =
# "推測・間接的示唆", 0.6 = "会話から強く示唆される") — a fact at or below
# that boundary was never more than a guess, or has decayed/been
# contradicted down to guess-level (Phase 1/2 above write straight into
# this same confidence column), so re-asking it isn't just "reusing the
# same threshold for consistency", it's the same semantic line memory
# extraction already draws.
_CONFIRM_CONFIDENCE_THRESHOLD = 0.5
# Categories with no decay rule at all (profile: (None, 1.0)) never get
# touched by Phase 1 above, so without a separate age-based check a
# profile fact could sit unconfirmed forever. 180 days matches the longest
# existing category decay window (devices/environment) — chosen so this
# check never fires *more* eagerly than decay already does for categories
# that have a decay rule, while still giving decay-exempt categories an
# eventual freshness check.
_CONFIRM_STALENESS_DAYS = 180


async def get_confirmation_candidates(jwt: str) -> list[dict[str, Any]]:
    """Return user_fact_items rows worth re-confirming with the user —
    low-confidence, contradiction-flagged, or long-unconfirmed facts.

    Deliberately only considers rows that already have a value (a null
    field is a *missing* fact, handled by active_inquiry.get_null_fields()
    instead — a different question shape: "I don't know X yet" vs "you
    told me X, is that still right?"). Returned rows are shaped compatibly
    with get_null_fields()'s dicts (source/category/key/id) so
    active_inquiry.py can pool and rank both kinds of candidate together,
    plus the extra fields (value/confidence/confirm_reason) a confirmation
    question actually needs.
    """
    try:
        facts = await rest_select(jwt, "user_fact_items", {
            "select": "*",
            "is_deleted": "eq.false",
        })
        if not isinstance(facts, list):
            return []
    except Exception:
        logger.exception("memory_validator: failed to fetch confirmation candidates")
        return []

    now = datetime.now(timezone.utc)
    candidates: list[dict[str, Any]] = []
    for item in facts:
        if item.get("value") is None:
            continue

        confidence = float(item.get("confidence") if item.get("confidence") is not None else 1.0)
        reason: str | None = None
        if confidence < _CONFIRM_CONFIDENCE_THRESHOLD:
            reason = "low_confidence"
        elif item.get("is_stale"):
            reason = "flagged_stale"
        else:
            updated_str = item.get("updated_at")
            if updated_str:
                try:
                    updated_at = datetime.fromisoformat(str(updated_str).replace("Z", "+00:00"))
                    if (now - updated_at).days >= _CONFIRM_STALENESS_DAYS:
                        reason = "long_unupdated"
                except ValueError:
                    pass

        if reason is None:
            continue

        candidates.append({
            "source": "user_fact_items_confirm",
            "category": item.get("category"),
            "key": item.get("key"),
            "id": item.get("id"),
            "value": item.get("value"),
            "confidence": confidence,
            "confirm_reason": reason,
        })

    return candidates


def _importance_adjusted_decay(
    base_decay_days: int, base_decay_factor: float, importance_score: float
) -> tuple[int, float]:
    importance = max(0.0, min(1.0, importance_score))
    effective_days = round(base_decay_days * (1.0 + importance * _IMPORTANCE_DECAY_ONSET_EXTENSION))
    severity = 1.0 - base_decay_factor
    dampened_severity = severity * (1.0 - importance * _IMPORTANCE_DECAY_SEVERITY_DAMPENING)
    effective_factor = 1.0 - dampened_severity
    return effective_days, effective_factor


# Phase B8: time-aware search ranking, built as an *extension* of the decay
# framework above rather than a second decay curve (explicit task
# requirement) — reuses _DECAY_RULES and _importance_adjusted_decay()
# exactly as Phase 1 (confidence decay) does, so search ranking and the
# daily validate_all_facts() batch job can never disagree about what
# "old" means for a given category/importance combination.
#
# The batch job applies decay as a single discrete step once age crosses
# the (importance-adjusted) decay_days threshold, multiplying confidence
# by decay_factor once per crossing (and each such write resets updated_at,
# restarting the clock — see phase_b8_report.md section 1 for the full
# trace of why this is a discrete geometric decay in decay_days-sized
# steps). Ranking needs a smooth, real-time, non-mutating signal instead
# (it must never write to the DB, and re-computing "how many times would
# the batch job have applied by now" from a single updated_at timestamp
# would require replaying history this function doesn't have). The
# continuous curve below is the natural generalization of that discrete
# step: it returns exactly decay_factor at age == decay_days (matching the
# batch job's first step), decay_factor**2 at age == 2*decay_days (matching
# a hypothetical second step), and interpolates smoothly in between and
# beyond, rather than jumping stepwise. Below the onset threshold it
# returns 1.0 (no decay at all yet), identically to the batch job's own
# gate (`if age_days < decay_days: continue`).
def compute_freshness_multiplier(
    category: str, *, age_days: float, importance_score: float
) -> float:
    """Return a 0..1 multiplier reflecting how "fresh" a fact is, purely as
    a function of elapsed time since it was last created/confirmed
    (age_days, expected to be computed from updated_at — see
    memory_search.py's _freshness_weighted_score). 1.0 means "no time-based
    discount at all", which is always the answer for a no-decay category
    (e.g. profile) regardless of age — requirement: permanent facts must
    never be unfairly penalized just for being old.
    """
    rule = _DECAY_RULES.get(category)
    if rule is None or rule[0] is None:
        return 1.0

    base_decay_days, base_decay_factor = rule
    decay_days, decay_factor = _importance_adjusted_decay(base_decay_days, base_decay_factor, importance_score)
    if age_days < decay_days or decay_days <= 0:
        return 1.0

    return decay_factor ** (age_days / decay_days)


async def validate_all_facts(jwt: str) -> dict[str, Any]:
    """
    Full daily validation pass:
    1. Decay confidence for facts older than their category threshold
    2. Detect contradictions via LLM for recently changed facts
    3. Mark logical deletion when importance × confidence < threshold
    4. Physical delete rows logically deleted 30+ days ago
    """
    result: dict[str, Any] = {
        "decayed": 0,
        "contradictions": 0,
        "logically_deleted": 0,
        "physically_deleted": 0,
        "errors": 0,
    }

    try:
        facts = await rest_select(jwt, "user_fact_items", {
            "select": "*",
            "is_deleted": "eq.false",
            "order": "category.asc,updated_at.asc",
        })
        if not isinstance(facts, list):
            facts = []
    except Exception:
        logger.exception("memory_validator: failed to fetch facts")
        return result

    now = datetime.now(timezone.utc)

    # ── Phase 1: Confidence decay ─────────────────────────────────────────────
    for item in facts:
        try:
            category = item.get("category") or ""
            rule = _DECAY_RULES.get(category)
            if rule is None or rule[0] is None:
                continue

            base_decay_days, base_decay_factor = rule
            updated_str = item.get("updated_at")
            if not updated_str:
                continue

            importance = float(item.get("importance_score") or 0.5)
            decay_days, decay_factor = _importance_adjusted_decay(
                base_decay_days, base_decay_factor, importance
            )

            updated_at = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            if (now - updated_at).days < decay_days:
                continue

            old_conf = float(item.get("confidence") or 1.0)
            new_conf = round(old_conf * decay_factor, 4)
            if abs(new_conf - old_conf) < 0.001:
                continue

            await rest_update(jwt, "user_fact_items", {"confidence": new_conf},
                              {"id": f"eq.{item['id']}"})
            item["confidence"] = new_conf
            result["decayed"] += 1
            logger.debug(
                "memory_validator: decayed %s/%s %.3f→%.3f",
                category, item.get("key"), old_conf, new_conf,
            )
        except Exception:
            logger.exception("memory_validator: decay error item=%s", item.get("id"))
            result["errors"] += 1

    # ── Phase 2: Contradiction detection (LLM, budget-limited) ───────────────
    recent_cutoff = (now - timedelta(days=7)).isoformat()
    try:
        history_rows = await rest_select(jwt, "user_fact_history", {
            "select": "fact_item_id,old_value,new_value",
            "created_at": f"gte.{recent_cutoff}",
            "order": "created_at.desc",
        })
        if not isinstance(history_rows, list):
            history_rows = []
    except Exception:
        logger.warning("memory_validator: could not fetch history")
        history_rows = []

    # Collect the most recent change per fact item (first occurrence wins since
    # history is ordered desc)
    changed: dict[str, dict[str, str]] = {}
    for row in history_rows:
        fid = row.get("fact_item_id")
        if not fid or fid in changed:
            continue
        old_v = row.get("old_value")
        new_v = row.get("new_value")
        if old_v is not None and new_v is not None and old_v != new_v:
            changed[fid] = {"old_value": str(old_v), "new_value": str(new_v)}

    facts_by_id: dict[str, dict] = {
        item["id"]: item for item in facts if item.get("id")
    }
    candidates = [
        (fid, info) for fid, info in changed.items() if fid in facts_by_id
    ][:_MAX_CONTRADICTION_CHECKS]

    for fid, info in candidates:
        fact = facts_by_id[fid]
        try:
            is_contradiction = await _check_contradiction(
                category=fact.get("category") or "",
                key=fact.get("key") or "",
                old_value=info["old_value"],
                new_value=info["new_value"],
            )
            if not is_contradiction:
                continue

            result["contradictions"] += 1
            old_conf = float(fact.get("confidence") or 1.0)
            reduced_conf = max(0.1, round(old_conf * 0.7, 4))
            await rest_update(jwt, "user_fact_items",
                              {"confidence": reduced_conf, "is_stale": True},
                              {"id": f"eq.{fid}"})
            fact["confidence"] = reduced_conf
            logger.info(
                "memory_validator: contradiction flagged %s/%s conf %.3f→%.3f",
                fact.get("category"), fact.get("key"), old_conf, reduced_conf,
            )
        except Exception:
            logger.exception("memory_validator: contradiction check error fid=%s", fid)
            result["errors"] += 1

    # ── Phase 3: Logical deletion ─────────────────────────────────────────────
    for item in facts:
        try:
            importance = float(item.get("importance_score") or 0.5)
            confidence = float(item.get("confidence") or 1.0)
            if importance * confidence >= _FORGET_THRESHOLD:
                continue
            await rest_update(jwt, "user_fact_items",
                              {"is_deleted": True, "deleted_at": now.isoformat()},
                              {"id": f"eq.{item['id']}"})
            result["logically_deleted"] += 1
            logger.info(
                "memory_validator: logically deleted %s/%s (%.3f×%.3f=%.3f)",
                item.get("category"), item.get("key"),
                importance, confidence, importance * confidence,
            )
        except Exception:
            logger.exception("memory_validator: logical delete error item=%s", item.get("id"))
            result["errors"] += 1

    # ── Phase 4: Physical deletion ────────────────────────────────────────────
    physical_cutoff = (now - timedelta(days=_PHYSICAL_DELETE_DAYS)).isoformat()
    try:
        await rest_delete(jwt, "user_fact_items", {
            "is_deleted": "eq.true",
            "deleted_at": f"lt.{physical_cutoff}",
        })
        result["physically_deleted"] = -1  # PostgREST DELETE returns no count
    except Exception:
        logger.exception("memory_validator: physical delete failed")
        result["errors"] += 1

    logger.info(
        "memory_validator: complete — decayed=%d contradictions=%d "
        "logically_deleted=%d errors=%d",
        result["decayed"], result["contradictions"],
        result["logically_deleted"], result["errors"],
    )
    return result


async def _check_contradiction(
    category: str,
    key: str,
    old_value: str,
    new_value: str,
) -> bool:
    """Return True if old_value and new_value are contradictory for this fact."""
    router = get_llm_router()
    prompt = (
        f"カテゴリ: {category}、キー: {key}\n"
        f"旧情報: {old_value[:200]}\n"
        f"新情報: {new_value[:200]}\n\n"
        "これらは論理的に矛盾していますか？\n"
        "矛盾している場合は「YES」のみ、矛盾していない（更新・補足）場合は「NO」のみ返してください。"
    )
    try:
        answer = await router.chat(
            TaskType.ROUTING,
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=5,
        )
        return answer.strip().upper().startswith("YES")
    except Exception:
        logger.exception("memory_validator: LLM contradiction check failed")
        return False  # fail-open: assume no contradiction
