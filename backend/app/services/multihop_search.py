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
#
# Phase B8: the same LLM call also judges whether the query is asking
# about current validity ("今も有効?"/"まだ続いてる?" — time-sensitive
# queries per phase_b8_report.md section 2). This was deliberately folded
# into decompose_query()'s existing response schema rather than added as a
# second LLM call — the task explicitly asked for a new dedicated call to
# be a last resort, and this question ("does the query need special
# handling?") is answered by the exact same classification pass that
# already runs on every turn for B7, so there's no marginal LLM round trip
# for this feature at all, on either the simple or complex path.
#
# Phase B9: knowledge_graph.py's entity/relation graph can optionally
# surface a short "known relations" hint here too, the same way
# recent_topic_labels already does (_format_topic_hint below) — plain
# substring matching against the query, computed entirely outside this
# module with no LLM call of its own, just appended as one more optional
# block in the same prompt this function already sends.

import asyncio
import json
import logging
from dataclasses import dataclass
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
    "あなたはシグマリスの記憶検索の前処理システムです。ユーザーの質問について、"
    "(1)単一の検索で答えられる単純な質問か、複数の異なる情報を組み合わせないと"
    "答えられない複雑な質問かを判定し、複雑な場合はそれぞれ単独で検索可能なサブ"
    "クエリに分解してください。(2)また、質問が「今も有効か」「まだ続いている"
    "か」といった、情報の現在時点での有効性を問うものかどうかも判定してくださ"
    "い。必ず有効なJSONのみを返してください。"
)

_DECOMPOSE_PROMPT = """ユーザーの質問:
{query}
{topic_hint}{entity_hint}
---
この質問について、以下の2点を判定してください。

**1. 分解の要否**: 複数の異なる記憶(事実)を組み合わせないと答えられない複雑な
質問であるかを判定してください。単一の話題についての単純な質問(例:「私の趣味
は何でしたっけ」)や、単なる雑談・挨拶では分解しないでください。

**2. 時系列的な性質**: 質問が「今も」「まだ」「最近は」「変わっていない?」のよ
うに、記憶している情報が現在時点でも有効かどうかを問うものであれば
time_sensitiveをtrueにしてください。単なる過去の事実の確認(例:「前に何て言っ
てたっけ」)はtime_sensitiveには含めません。

複雑と判定した場合は、以下のJSONを出力してください:
{{
  "needs_decomposition": true,
  "sub_queries": ["サブクエリ1", "サブクエリ2", "..."],
  "time_sensitive": true または false
}}
サブクエリは最大{max_subqueries}個までとし、それぞれ単独の検索質問として意味が
通るようにしてください(元の質問の一部をそのまま使ってよい)。

単純な質問の場合は以下を返してください(time_sensitiveの判定は分解の要否と独立
に行うこと):
{{"needs_decomposition": false, "time_sensitive": true または false}}"""


def _format_topic_hint(recent_topic_labels: list[str] | None) -> str:
    if not recent_topic_labels:
        return ""
    joined = " → ".join(recent_topic_labels)
    return f"\n直近の話題の推移(参考、無理に使う必要はない): {joined}\n"


def _format_entity_hint(entity_hint: str | None) -> str:
    if not entity_hint:
        return ""
    return f"\n{entity_hint}\n"


@dataclass(frozen=True)
class QueryAnalysis:
    sub_queries: list[str] | None
    time_sensitive: bool


_NOT_DECOMPOSED = QueryAnalysis(sub_queries=None, time_sensitive=False)


async def decompose_query(
    query: str,
    *,
    recent_topic_labels: list[str] | None = None,
    entity_hint: str | None = None,
) -> QueryAnalysis:
    """Ask the LLM (one combined call) whether `query` needs multi-hop
    decomposition and whether it's asking about current validity
    (Phase B8's time_sensitive flag — see this module's docstring for why
    it rides on this same call instead of a new one).

    sub_queries is None when a single search is sufficient (the common
    case) — callers should fall back to a plain search_relevant_memories()
    call. time_sensitive is independent of sub_queries: a simple
    single-topic question can still be time-sensitive (e.g. "それって今も
    変わってない?").

    entity_hint (Phase B9): an optional, pre-formatted "known relations"
    string from knowledge_graph.build_entity_hint() — purely textual,
    computed with no LLM call of its own (see this module's docstring).
    """
    cleaned = query.strip()
    if not cleaned:
        return _NOT_DECOMPOSED

    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.QUERY_DECOMPOSITION,
            [
                {"role": "system", "content": _DECOMPOSE_SYSTEM},
                {"role": "user", "content": _DECOMPOSE_PROMPT.format(
                    query=cleaned,
                    topic_hint=_format_topic_hint(recent_topic_labels),
                    entity_hint=_format_entity_hint(entity_hint),
                    max_subqueries=_MAX_SUBQUERIES,
                )},
            ],
            temperature=0.1,
            max_tokens=300,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return _NOT_DECOMPOSED

        time_sensitive = bool(parsed.get("time_sensitive"))

        if not parsed.get("needs_decomposition"):
            return QueryAnalysis(sub_queries=None, time_sensitive=time_sensitive)

        raw_sub_queries = parsed.get("sub_queries")
        if not isinstance(raw_sub_queries, list):
            return QueryAnalysis(sub_queries=None, time_sensitive=time_sensitive)

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
            return QueryAnalysis(sub_queries=None, time_sensitive=time_sensitive)

        return QueryAnalysis(sub_queries=sub_queries, time_sensitive=time_sensitive)
    except Exception:
        logger.exception("multihop_search: decompose_query failed, falling back to single query")
        return _NOT_DECOMPOSED


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
    entity_hint: str | None = None,
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Search relevant memories, transparently decomposing `query` into
    sub-queries first when the LLM judges it necessary, and strengthening
    the freshness ranking weight (Phase B8) when the query is judged to be
    asking about current validity.

    Returns (memories, was_decomposed, time_sensitive). Both flags are
    purely informational for a caller that only wants the memories, but
    Phase B11's calibrated abstention reuses them directly (already
    computed here at zero marginal cost) to pick a stricter or more
    lenient confidence threshold — see memory_confidence.py.

    entity_hint (Phase B9): see decompose_query()'s docstring.
    """
    analysis = await decompose_query(
        query, recent_topic_labels=recent_topic_labels, entity_hint=entity_hint
    )
    if not analysis.sub_queries:
        single = await search_relevant_memories(
            query,
            user_id,
            threshold=threshold,
            limit=limit,
            jwt=jwt,
            time_sensitive_query=analysis.time_sensitive,
        )
        return single, False, analysis.time_sensitive

    # Independent searches — fan out concurrently so added latency stays
    # close to the single slowest sub-query, not sub_queries-count x a
    # single search's latency.
    results = await asyncio.gather(
        *[
            search_relevant_memories(
                sq,
                user_id,
                threshold=threshold,
                limit=limit,
                jwt=jwt,
                time_sensitive_query=analysis.time_sensitive,
            )
            for sq in analysis.sub_queries
        ],
        return_exceptions=True,
    )
    ranked_lists: list[list[dict[str, Any]]] = []
    for sq, result in zip(analysis.sub_queries, results):
        if isinstance(result, BaseException):
            logger.exception("multihop_search: sub-query search failed query=%r", sq, exc_info=result)
            continue
        ranked_lists.append(result)

    if not ranked_lists:
        return [], True, analysis.time_sensitive

    merged = _rrf_merge_ranked_lists(ranked_lists, limit=_MULTIHOP_RESULT_LIMIT)
    logger.info(
        "multihop_search: decomposed into %d sub-queries, merged=%d results",
        len(analysis.sub_queries), len(merged),
    )
    return merged, True, analysis.time_sensitive
