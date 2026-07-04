from __future__ import annotations

# Phase B11: calibrated abstention.
#
# Deliberately zero new LLM calls (the task's overriding constraint, given
# B7 and B10 already added two dedicated calls to the response path). This
# module is pure rule-based arithmetic over data that's already computed
# by the time it's called:
#   - each returned memory row's own `similarity` (set by the search RPCs,
#     untouched by B17/B13/B8's ranking weights or B10's listwise rerank —
#     those all sort by a *derived* score but never overwrite the row's
#     original similarity field) and `match_source` (Phase B4, tags
#     "vector"/"trgm"/"both")
#   - multihop_search.decompose_query()'s existing needs_decomposition
#     (Phase B7) and time_sensitive (Phase B8) judgments, already computed
#     on every turn regardless of this feature — reused here as the
#     "question category" axis the task asked for, at zero marginal cost.
#
# Why similarity rather than the ranking score B17/B13/B8/B10 sort by:
# that score's scale and meaning depends on which tier/path produced it
# (a near-exact trgm hit's base score is its raw similarity; a normal RRF-
# tier hit's base score is a tiny 1/(_RRF_K+rank)-derived number; B10's
# rerank replaces that again with an LLM-rank-derived RRF score) — there is
# no single consistently-scaled "confidence" number across all paths.
# similarity, in contrast, is always in [0, 1] and always means the same
# thing regardless of which tier or rerank path a result took, which is
# exactly what a fixed threshold needs to be meaningful.

from typing import Any, Literal

from app.services.memory_search import _TRGM_HIGH_CONFIDENCE_SIMILARITY

ConfidenceTier = Literal["confident", "low_confidence", "no_evidence"]

# search_relevant_memories() is always called with threshold=0.7 (the
# vector-search floor) throughout this codebase (orchestrator/service.py,
# multihop_search.py) — nothing below that ever reaches these functions at
# all. These thresholds are defined as a margin *above* that floor: a
# result that only barely cleared the existing filter is exactly the
# "technically matched, but weakly" case abstention needs to catch.
#
# Baseline margin (+0.08) chosen conservatively — small enough that most
# genuinely-relevant single-topic matches (which in practice cluster
# noticeably above the bare 0.7 floor once a fact actually addresses the
# question) still count as confident, per the requirement to avoid
# over-hedging ordinary queries.
_ABSTAIN_VECTOR_THRESHOLD_BASELINE = 0.78

# Stricter margin (+0.15) for multihop/time-sensitive queries: multihop
# questions synthesize an answer across multiple facts (a weak supporting
# match on either side makes the *combined* claim riskier, not just one
# half of it), and time-sensitive questions are exactly the "is this still
# true" failure mode B8 was built to address — both warrant a higher bar
# before letting Sigmaris answer assertively.
_ABSTAIN_VECTOR_THRESHOLD_STRICT = 0.85

# Trigram similarity has no comparably continuous "how much better than
# the floor" gradient the way cosine similarity does — B1 already defined
# 0.5 as the near-exact/high-confidence bar (_TRGM_HIGH_CONFIDENCE_
# SIMILARITY, used to give keyword hits their own priority tier). Reusing
# that existing, already-validated bar directly rather than inventing a
# second trgm threshold. Applied uniformly regardless of query category —
# narrowing it further for the strict case would risk excluding
# legitimate exact-keyword hits, which is a worse failure mode than the
# vector case (see phase_b11_report.md section 1 for the full reasoning).
_ABSTAIN_TRGM_THRESHOLD = _TRGM_HIGH_CONFIDENCE_SIMILARITY

_NO_EVIDENCE_NOTE = (
    "[記憶の確信度に関する注意]\n"
    "今回の発言に関連する具体的な記憶は見つかりませんでした。もし何かを尋ねら"
    "れている場合は、記憶にない内容を断定したり作話したりせず、正直に「その件"
    "については、まだ十分な情報がありません」のように伝えてください。単なる雑"
    "談であれば、この注意は無視して構いません。"
)

_LOW_CONFIDENCE_NOTE = (
    "[記憶の確信度に関する注意]\n"
    "以下の記憶は、今回の質問との関連性が高いとは言い切れません。persona.md"
    "5章の確信度の伝え方(仮説層)に従い、「もしかしたら〜かもしれません」「ま"
    "だ確証はないんですが」のように必ずヘッジして述べてください。断定的な言い"
    "切りは避けてください。"
)


def classify_confidence_tier(
    memories: list[dict[str, Any]],
    *,
    is_multihop: bool,
    is_time_sensitive: bool,
) -> ConfidenceTier:
    """Classify how confidently the top search result supports answering
    the query, using only data already computed by search_relevant_
    memories()/search_with_decomposition() — no LLM call.

    Only the top-ranked result is examined: if the single strongest
    supporting fact is weak, hedging the whole answer is appropriate
    regardless of how many additional weaker facts also came back
    (the common RAG-abstention practice of gating on top-1 relevance).
    """
    if not memories:
        return "no_evidence"

    top = memories[0]
    similarity = float(top.get("similarity") or 0.0)
    match_source = top.get("match_source")

    if match_source == "trgm":
        floor = _ABSTAIN_TRGM_THRESHOLD
    else:
        strict = is_multihop or is_time_sensitive
        floor = _ABSTAIN_VECTOR_THRESHOLD_STRICT if strict else _ABSTAIN_VECTOR_THRESHOLD_BASELINE

    return "confident" if similarity >= floor else "low_confidence"


def confidence_guidance_note(tier: ConfidenceTier) -> str | None:
    """Return the prompt note for a given tier, or None for "confident"
    (no change to existing behavior — the whole point of calibration is
    that a genuinely well-supported answer isn't hedged at all)."""
    if tier == "no_evidence":
        return _NO_EVIDENCE_NOTE
    if tier == "low_confidence":
        return _LOW_CONFIDENCE_NOTE
    return None
