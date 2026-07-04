from __future__ import annotations

# Phase B7: multi-hop query decomposition.
#
# search_relevant_memories() (Phase B1's hybrid vector+trgm search) answers
# a single query well, but a question that genuinely needs two or more
# distinct facts combined ("AdFlow AIの件で前回決めた方針と、シグマリスの技
# 術選定は矛盾していない?" — a decision-log fact and a self-model/tech-stack
# fact, not one fact that mentions both) tends to under-serve one side of
# the question: a single embedding/trgm query is pulled toward whichever
# topic dominates the sentence, and the other side's facts often fall
# below the similarity threshold entirely.
#
# This module sits in front of search_relevant_memories() in the critical
# response path (unlike B2/B6's fire-and-forget detectors, this one's
# latency is user-facing — see phase_b7_report.md section 3): it asks the
# LLM, in one combined call, whether the query needs decomposition at all
# and — only if so — what the sub-queries should be. Simple questions pay
# for exactly one cheap classification call and then proceed through the
# unchanged single-query path; only genuinely compound questions pay for
# the extra fan-out searches.

import asyncio
import json
import logging
from typing import Any

from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_search import _RRF_K, search_relevant_memories

logger = logging.getLogger(__name__)

# Requirement: cap sub-query count so a single question can't explode into
# an unbounded number of searches. 4 was chosen as "a small handful of
# genuinely distinct sub-topics" — the motivating example (AdFlow AIの方針
# + 技術選定) only needs 2; 4 leaves headroom for a 3-4-way comparison
# question without inviting the LLM to over-decompose a moderately complex
# single-topic question into many near-duplicate sub-queries.
_MAX_SUBQUERIES = 4

# Requirement 3 (bounded merged result size): each sub-query search still
# requests memory_search.py's own default limit (5) individually, but the
# *combined*, deduplicated result is capped here rather than left at
# up to len(sub_queries)*5 — keeps the injected context roughly
# proportional to "a few topics' worth of facts", not "every sub-query's
# full result set concatenated". Set higher than the single-query default
# (5) since a multi-hop question legitimately needs to cover more distinct
# facts than a single-topic one, but still bounded.
_MULTIHOP_RESULT_LIMIT = 8

_DECOMPOSE_SYSTEM = (
    "あなたはシグマリスの記憶検索の前処理システムです。ユーザーの質問が、単一の"
    "検索で答えられる単純な質問か、複数の異なる情報を組み合わせないと答えられな"
    "い複雑な質問かを判定します。複雑な場合のみ、それぞれ単独で検索可能なサブク"
    "エリに分解してください。必ず有効なJSONのみを返してください。"
)

_DECOMPOSE_PROMPT = """ユーザーの質問:
{query}
{topic_hint}
---
この質問が、複数の異なる記憶(事実)を組み合わせないと答えられない複雑な質問で
あるかを判定してください。単一の話題についての単純な質問(例:「私の趣味は何で
したっけ」)や、単なる雑談・挨拶では分解しないでください。

複雑と判定した場合のみ、以下のJSONを出力してください:
{{
  "needs_decomposition": true,
  "sub_queries": ["サブクエリ1", "サブクエリ2", "..."]
}}
サブクエリは最大{max_subqueries}個までとし、それぞれ単独の検索質問として意味が
通るようにしてください(元の質問の一部をそのまま使ってよい)。

単純な質問の場合は以下のみ返してください:
{{"needs_decomposition": false}}"""


def _format_topic_hint(recent_topic_labels: list[str] | None) -> str:
    if not recent_topic_labels:
        return ""
    joined = " → ".join(recent_topic_labels)
    return f"\n直近の話題の推移(参考、無理に使う必要はない): {joined}\n"


async def decompose_query(
    query: str,
    *,
    recent_topic_labels: list[str] | None = None,
) -> list[str] | None:
    """Ask the LLM whether `query` needs multi-hop decomposition.

    Returns None when a single search is sufficient (the common case) —
    callers should fall back to a plain search_relevant_memories() call.
    Returns a list of 2-_MAX_SUBQUERIES sub-queries when decomposition is
    judged necessary.
    """
    cleaned = query.strip()
    if not cleaned:
        return None

    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.QUERY_DECOMPOSITION,
            [
                {"role": "system", "content": _DECOMPOSE_SYSTEM},
                {"role": "user", "content": _DECOMPOSE_PROMPT.format(
                    query=cleaned,
                    topic_hint=_format_topic_hint(recent_topic_labels),
                    max_subqueries=_MAX_SUBQUERIES,
                )},
            ],
            temperature=0.1,
            max_tokens=300,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict) or not parsed.get("needs_decomposition"):
            return None

        raw_sub_queries = parsed.get("sub_queries")
        if not isinstance(raw_sub_queries, list):
            return None

        sub_queries = [
            str(sq).strip()
            for sq in raw_sub_queries
            if isinstance(sq, str) and str(sq).strip()
        ]
        # De-dup while preserving order — a sloppy decomposition
        # occasionally repeats the same sub-query verbatim.
        sub_queries = list(dict.fromkeys(sub_queries))[:_MAX_SUBQUERIES]

        # A single (or zero) usable sub-query isn't a real decomposition —
        # treat it the same as "not needed" rather than paying for an
        # extra search round-trip that a plain single query would answer
        # just as well.
        if len(sub_queries) < 2:
            return None

        return sub_queries
    except Exception:
        logger.exception("multihop_search: decompose_query failed, falling back to single query")
        return None


def _rrf_merge_ranked_lists(
    ranked_lists: list[list[dict[str, Any]]], *, limit: int
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion across N already-ranked result lists (each
    itself already RRF/importance/adoption-ranked by search_relevant_
    memories() — this is a second, coarser fusion pass across sub-query
    result sets, not a replacement for that per-query ranking). Reuses
    memory_search.py's own _RRF_K rather than a second magic number."""
    scores: dict[str, float] = {}
    rows_by_id: dict[str, dict[str, Any]] = {}
    for ranked_list in ranked_lists:
        for rank, row in enumerate(ranked_list, start=1):
            row_id = row.get("id")
            if not row_id:
                continue
            scores[row_id] = scores.get(row_id, 0.0) + 1.0 / (_RRF_K + rank)
            rows_by_id.setdefault(row_id, row)

    ordered_ids = sorted(scores, key=lambda row_id: scores[row_id], reverse=True)
    return [rows_by_id[row_id] for row_id in ordered_ids[:limit]]


async def search_with_decomposition(
    query: str,
    user_id: str,
    *,
    jwt: str,
    threshold: float = 0.7,
    limit: int = 5,
    recent_topic_labels: list[str] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Search relevant memories, transparently decomposing `query` into
    sub-queries first when the LLM judges it necessary.

    Returns (memories, was_decomposed). was_decomposed is purely
    informational (logging/testing) — callers that only want the memories
    can ignore it.
    """
    sub_queries = await decompose_query(query, recent_topic_labels=recent_topic_labels)
    if not sub_queries:
        single = await search_relevant_memories(query, user_id, threshold=threshold, limit=limit, jwt=jwt)
        return single, False

    # Independent searches — fan out concurrently so added latency stays
    # close to the single slowest sub-query, not sub_queries-count x a
    # single search's latency.
    results = await asyncio.gather(
        *[
            search_relevant_memories(sq, user_id, threshold=threshold, limit=limit, jwt=jwt)
            for sq in sub_queries
        ],
        return_exceptions=True,
    )
    ranked_lists: list[list[dict[str, Any]]] = []
    for sq, result in zip(sub_queries, results):
        if isinstance(result, BaseException):
            logger.exception("multihop_search: sub-query search failed query=%r", sq, exc_info=result)
            continue
        ranked_lists.append(result)

    if not ranked_lists:
        return [], True

    merged = _rrf_merge_ranked_lists(ranked_lists, limit=_MULTIHOP_RESULT_LIMIT)
    logger.info(
        "multihop_search: decomposed into %d sub-queries, merged=%d results",
        len(sub_queries), len(merged),
    )
    return merged, True
