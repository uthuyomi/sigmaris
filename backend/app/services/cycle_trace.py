from __future__ import annotations

# Phase R-1 (docs/sigmaris/phase_r_report.md): read-only trace helpers that
# walk the existing per-stage "reference to the previous stage" links (B4's
# thread_id/invocation_id, B2's source_experience_ids, A3's memory_refs,
# B14's supporting_decision_ids, B16's evidence_refs/goal_fact_ids) to
# reconstruct, on demand, which upstream records a given Memory/Belief/
# Policy row traces back to.
#
# Deliberately NOT a persisted/cached trace, and deliberately NOT built on
# a new unifying id: every call re-reads the current state of these
# reference columns, so a trace always reflects the live data (including
# any supersede/consolidation that happened since the referencing row was
# written). See phase_r_report.md section 1 for why a single cycle_id was
# rejected in favor of this loose-coupling approach.

from typing import Any

from app.services.decision_log import get_decisions_by_ids, get_preference_patterns_by_ids
from app.services.experience_layer import get_experiences_by_ids
from app.services.goal_alignment import get_goal_alignment_flags_by_ids
from app.services.topic_tracker import get_topics_by_ids
from app.services.user_fact_data import get_fact_items_by_ids


async def trace_memory_to_experience(fact_item: dict[str, Any]) -> dict[str, Any]:
    """Memory -> Experience (one hop).

    Takes an already-fetched user_fact_items row (not an id) since callers
    generically already have it in hand (e.g. iterating
    get_fact_items_for_user() results) and re-fetching it here would be a
    redundant round-trip.

    Returns both possible origins a fact can carry (phase_r_report.md
    section 2's inventory) -- not mutually exclusive in principle, though
    in practice a given fact currently has one or the other, never both:
      - direct_turn: the thread_id/invocation_id of the conversation turn
        memory_extractor.py wrote it from directly (Phase B4).
      - source_experiences: the sigmaris_experience rows
        consolidate_episodic_memory() (Phase B2) derived it from, if any.
    """
    direct_turn = None
    if fact_item.get("thread_id") or fact_item.get("invocation_id"):
        direct_turn = {
            "thread_id": fact_item.get("thread_id"),
            "invocation_id": fact_item.get("invocation_id"),
        }

    source_experience_ids = fact_item.get("source_experience_ids")
    source_experiences = (
        await get_experiences_by_ids(source_experience_ids)
        if isinstance(source_experience_ids, list) and source_experience_ids
        else []
    )

    return {
        "fact_id": fact_item.get("id"),
        "direct_turn": direct_turn,
        "source_experiences": source_experiences,
    }


async def trace_belief_to_memory(pattern_id: str) -> dict[str, Any]:
    """Belief Update -> Memory (two hops, via the Action/decision_log
    stage in between).

    A sigmaris_user_preference_patterns row (Phase B14) doesn't reference
    user_fact_items directly -- it references the sigmaris_decision_log
    rows it was inferred from via supporting_decision_ids, and each of
    *those* decisions references the Memory-stage facts it relied on via
    its own memory_refs (Phase A3/B4). This walks both hops and returns
    the deduplicated union of Memory rows at the end of the chain, plus
    the intermediate decisions themselves (so the Action-stage link isn't
    lost along the way).
    """
    patterns = await get_preference_patterns_by_ids([pattern_id])
    pattern = patterns[0] if patterns else None
    if not pattern:
        return {"pattern_id": pattern_id, "found": False}

    supporting_decision_ids = pattern.get("supporting_decision_ids")
    supporting_decision_ids = (
        supporting_decision_ids if isinstance(supporting_decision_ids, list) else []
    )
    decisions = await get_decisions_by_ids(supporting_decision_ids)

    fact_ids: list[str] = []
    for decision in decisions:
        refs = decision.get("memory_refs")
        if isinstance(refs, list):
            fact_ids.extend(ref for ref in refs if isinstance(ref, str))
    fact_ids = list(dict.fromkeys(fact_ids))
    facts = await get_fact_items_by_ids(fact_ids)

    return {
        "pattern_id": pattern_id,
        "found": True,
        "pattern_key": pattern.get("pattern_key"),
        "supporting_decisions": decisions,
        "traced_facts": facts,
    }


async def trace_policy_to_evidence(flag_id: str) -> dict[str, Any]:
    """Policy Update -> its evidence (Action/decision_log + topic_log) and
    -> Memory (via Phase R-1's goal_fact_ids gap-fill, section 3).

    A sigmaris_goal_alignment_flags row (Phase B16) references its
    supporting evidence via evidence_refs (a mixed decision_log/topic_log
    id set, resolved here by trying both tables) and the specific goal
    fact(s) it concerns via goal_fact_ids.
    """
    flags = await get_goal_alignment_flags_by_ids([flag_id])
    flag = flags[0] if flags else None
    if not flag:
        return {"flag_id": flag_id, "found": False}

    evidence_refs = flag.get("evidence_refs")
    evidence_refs = [ref for ref in evidence_refs if isinstance(ref, str)] if isinstance(evidence_refs, list) else []
    # evidence_refs mixes decision_log and topic_log ids (see
    # goal_alignment.py's evidence_ids = decision_ids | topic_ids) with no
    # marker for which table a given id belongs to -- querying both tables
    # with the full id set and letting each table's own id=in.(...) filter
    # return only its own matches is the simplest correct way to split
    # them back out, at the cost of one harmless "no match" lookup per id
    # against whichever table it doesn't belong to.
    decisions = await get_decisions_by_ids(evidence_refs)
    topics = await get_topics_by_ids(evidence_refs)

    goal_fact_ids = flag.get("goal_fact_ids")
    goal_fact_ids = goal_fact_ids if isinstance(goal_fact_ids, list) else []
    goal_facts = await get_fact_items_by_ids(goal_fact_ids)

    return {
        "flag_id": flag_id,
        "found": True,
        "goal_reference": flag.get("goal_reference"),
        "evidence_decisions": decisions,
        "evidence_topics": topics,
        "goal_facts": goal_facts,
    }
