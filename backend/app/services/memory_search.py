from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.services.proactive.jwt_manager import get_sigmaris_jwt
from app.services.supabase_rest import get_current_user, rest_rpc, rest_select, rest_update

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 768
EMBED_BATCH_SIZE = 10

# Phase B1: hybrid search tuning. Trigram similarity scores for short
# Japanese/mixed-language strings rarely reach the 0.7+ range vector cosine
# similarity does, so this is a separate, much lower threshold — not the
# same `threshold` param search_relevant_memories() uses for vector search.
TRGM_MATCH_THRESHOLD = 0.15

# A trigram hit at or above this similarity is treated as a near-exact
# keyword/substring match (e.g. a literal product name) and is surfaced
# ahead of the RRF-ranked results, regardless of how the vector search
# ranked it — this is the direct fix for vector search missing proper
# nouns, see phase_b1_report.md section 2.
_TRGM_HIGH_CONFIDENCE_SIMILARITY = 0.5

# Standard Reciprocal Rank Fusion constant (the usual default is 60; it
# controls how much rank position 1 is favored over lower ranks — not
# sensitive to tune further for a candidate pool this small).
_RRF_K = 60

# Phase B17: how much user_fact_items.importance_score (0.0-1.0, already
# used by build_facts_context()'s top-N sort and memory_validator.py's
# logical-deletion threshold) nudges search ranking. A pure multiplier
# capped at +15% at importance=1.0 — small enough that it breaks ties among
# similarly-relevant results without overriding a real relevance gap
# (requirement 3: this must never make a clearly-worse match outrank a
# clearly-better one just because it's tagged more important). See
# phase_b17_report.md section 1 for the values actually tried.
_IMPORTANCE_RANKING_WEIGHT = 0.15

# The DB column's own default (202606270019_trend_memory.sql) — used when a
# row has no importance_score at all, which happens for every result until
# migration 202607090031 is applied (the RPCs simply won't return the
# field yet). Defaulting to the column's own neutral default means ranking
# behaves identically pre- and post-migration.
_DEFAULT_IMPORTANCE_SCORE = 0.5


def _importance_weighted_score(base_score: float, row: dict[str, Any]) -> float:
    importance = row.get("importance_score")
    importance = float(importance) if importance is not None else _DEFAULT_IMPORTANCE_SCORE
    return base_score * (1.0 + importance * _IMPORTANCE_RANKING_WEIGHT)


# Phase B13: implicit feedback from sigmaris_decision_log.memory_refs — how
# many *distinct* past decisions actually relied on a fact (populated by
# decision_log.py::recompute_adoption_counts(), a weekly batch job).
# Positive-only: a fact search surfaces but that has never appeared in any
# decision's memory_refs simply gets no boost at all — this must never
# become a penalty (see phase_b13_report.md section 1 for why "no evidence
# of adoption" isn't treated as "evidence of non-adoption"; that inference
# isn't supportable from this signal alone).
#
# Below this many distinct adoptions, treated as no signal — the same
# "don't trust sparse evidence" reasoning as Phase B14's
# _MIN_SUPPORTING_DECISIONS, kept at the same value for consistency across
# the B-group's evidence-gating philosophy.
_MIN_ADOPTION_COUNT_FOR_BOOST = 2

# adoption_count's effect saturates here — beyond this many distinct
# adoptions, no further boost. Keeps one very-frequently-cited fact from
# permanently dominating rankings regardless of relevance to the *current*
# query (requirement: this is a tie-breaker among similarly-relevant
# results, not a relevance override).
_ADOPTION_COUNT_SATURATION = 5

# Composes multiplicatively with _IMPORTANCE_RANKING_WEIGHT (see
# _apply_ranking_weights below), so kept smaller than it: the worst-case
# combined boost (importance=1.0 AND adoption_count>=saturation
# simultaneously) is (1.15)*(1.10)=1.265, a bounded ~27% ceiling rather than
# two independently-maxed 15% boosts compounding past 30%. See
# phase_b13_report.md section 2 for the empirical rank-gap values actually
# tried (0.10 chosen over 0.15/0.30, mirroring B17's own methodology).
_ADOPTION_RANKING_WEIGHT = 0.10


def _adoption_weighted_score(base_score: float, row: dict[str, Any]) -> float:
    adoption_count = int(row.get("adoption_count") or 0)
    if adoption_count < _MIN_ADOPTION_COUNT_FOR_BOOST:
        return base_score
    normalized = min(adoption_count, _ADOPTION_COUNT_SATURATION) / _ADOPTION_COUNT_SATURATION
    return base_score * (1.0 + normalized * _ADOPTION_RANKING_WEIGHT)


def _apply_ranking_weights(base_score: float, row: dict[str, Any]) -> float:
    """Phase B17 (importance_score) + Phase B13 (implicit adoption
    feedback), composed multiplicatively. Multiplication commutes, so
    application order doesn't change the result — importance is applied
    first simply to match the order these two features were built in."""
    score = _importance_weighted_score(base_score, row)
    score = _adoption_weighted_score(score, row)
    return score


# Lazily probed once per process: whether the local Ollama instance actually
# answers. Mirrors LLMRouter's _local_available pattern in local_llm.py —
# LOCAL_LLM_ENABLED=true alone doesn't guarantee Ollama is reachable, so a
# reachability probe gates the choice, not just the config flag.
_ollama_embed_available: bool | None = None

# Lazy singleton so we don't reconstruct an AsyncOpenAI client on every call
# (generate_embedding can now run on the hot path of every chat turn).
_openai_embed_client: AsyncOpenAI | None = None


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def _fact_embedding_text(item: dict[str, Any]) -> str:
    parts = [
        str(item.get("category") or "").strip(),
        str(item.get("key") or "").strip(),
        str(item.get("value") or "").strip(),
        str(item.get("notes") or "").strip(),
    ]
    return "\n".join(part for part in parts if part)


async def _probe_ollama_embed_available() -> bool:
    global _ollama_embed_available
    if _ollama_embed_available is None:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            _ollama_embed_available = response.is_success
        except Exception:
            _ollama_embed_available = False
        if not _ollama_embed_available:
            logger.warning(
                "memory_search: Ollama not reachable at %s — falling back to OpenAI embeddings.",
                settings.ollama_base_url,
            )
    return _ollama_embed_available


async def _generate_embedding_ollama(cleaned: str) -> list[float]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        response = await client.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/embeddings",
            json={
                "model": settings.ollama_embed_model,
                "prompt": cleaned,
            },
        )
    response.raise_for_status()
    data = response.json()
    embedding = data.get("embedding")
    if not isinstance(embedding, list):
        raise RuntimeError("Ollama embedding response did not include an embedding list.")

    values = [float(value) for value in embedding]
    if len(values) != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"Ollama embedding dimension mismatch: expected {EMBEDDING_DIMENSIONS}, got {len(values)}."
        )
    return values


async def _generate_embedding_openai(cleaned: str) -> list[float]:
    global _openai_embed_client
    if _openai_embed_client is None:
        _openai_embed_client = AsyncOpenAI(api_key=settings.openai_api_key)

    # `dimensions` truncates OpenAI's natively-1536-dim text-embedding-3-small
    # output to 768 (Matryoshka representation learning — officially
    # supported, not a hack), matching pgvector's `vector(768)` column and
    # search_fact_memory()'s fixed `vector(768)` RPC signature exactly, so no
    # schema or RPC change is needed to support this fallback.
    response = await _openai_embed_client.embeddings.create(
        model=settings.openai_embedding_model,
        input=cleaned,
        dimensions=EMBEDDING_DIMENSIONS,
    )
    values = [float(value) for value in response.data[0].embedding]
    if len(values) != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"OpenAI embedding dimension mismatch: expected {EMBEDDING_DIMENSIONS}, got {len(values)}."
        )
    return values


async def generate_embedding(text: str) -> list[float]:
    """Generate a 768-dim embedding, preferring local Ollama and falling
    back to OpenAI (dimensions-truncated to match) when Ollama is disabled
    or unreachable, so RAG search works regardless of LOCAL_LLM_ENABLED.
    """
    cleaned = text.strip()
    if not cleaned:
        return []

    if settings.local_llm_enabled and await _probe_ollama_embed_available():
        return await _generate_embedding_ollama(cleaned)

    if not settings.openai_api_key:
        logger.warning(
            "memory_search: no embedding backend available "
            "(Ollama disabled/unreachable, OPENAI_API_KEY unset) — skipping."
        )
        return []

    return await _generate_embedding_openai(cleaned)


async def _search_fact_memory_vector(
    token: str, embedding: list[float], user_id: str, threshold: float, limit: int
) -> list[dict[str, Any]]:
    result = await rest_rpc(
        token,
        "search_fact_memory",
        {
            "query_embedding": _vector_literal(embedding),
            "user_id_param": user_id,
            "match_threshold": threshold,
            "match_count": limit,
        },
    )
    rows = result if isinstance(result, list) else []
    rows.sort(key=lambda item: float(item.get("similarity") or 0.0), reverse=True)
    return rows


async def _search_fact_memory_trgm(
    token: str, query: str, user_id: str, limit: int
) -> list[dict[str, Any]]:
    cleaned = query.strip()
    if not cleaned:
        return []
    result = await rest_rpc(
        token,
        "search_fact_memory_trgm",
        {
            "query_text": cleaned,
            "user_id_param": user_id,
            "match_threshold": TRGM_MATCH_THRESHOLD,
            "match_count": limit,
        },
    )
    rows = result if isinstance(result, list) else []
    rows.sort(key=lambda item: float(item.get("similarity") or 0.0), reverse=True)
    return rows


def _merge_hybrid_results(
    vector_rows: list[dict[str, Any]], trgm_rows: list[dict[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion across the two ranked lists, with an explicit
    boost so a near-exact trigram/keyword hit is never buried beneath
    semantically-adjacent-but-wrong vector results (requirement: proper
    nouns like "ThinkPad T14" must surface even if the embedding missed
    them entirely)."""
    scores: dict[str, float] = {}
    rows_by_id: dict[str, dict[str, Any]] = {}
    vector_ids = {row["id"] for row in vector_rows if row.get("id")}
    trgm_ids = {row["id"] for row in trgm_rows if row.get("id")}
    for ranked_list in (vector_rows, trgm_rows):
        for rank, row in enumerate(ranked_list, start=1):
            row_id = row.get("id")
            if not row_id:
                continue
            scores[row_id] = scores.get(row_id, 0.0) + 1.0 / (_RRF_K + rank)
            existing = rows_by_id.get(row_id)
            if existing is None or float(row.get("similarity") or 0.0) > float(
                existing.get("similarity") or 0.0
            ):
                rows_by_id[row_id] = row

    # Phase B1 follow-up: tag which search path(s) produced each hit. Not
    # persisted anywhere — this is a lightweight debugging/tuning aid (see
    # phase_b4_report.md section 3) for eyeballing match_threshold/
    # _TRGM_HIGH_CONFIDENCE_SIMILARITY against real logs, not a feature in
    # its own right, so it isn't written to a table.
    for row_id, row in rows_by_id.items():
        in_vector = row_id in vector_ids
        in_trgm = row_id in trgm_ids
        row["match_source"] = "both" if in_vector and in_trgm else ("vector" if in_vector else "trgm")

    # Phase B17: importance_score nudges ordering *within* each tier (the
    # near-exact-keyword tier and the RRF-ranked tier) — it never moves a
    # result between tiers, so a highly-important-but-only-loosely-relevant
    # fact still can't outrank a genuine near-exact keyword match.
    high_confidence_ids = sorted(
        (
            row["id"]
            for row in trgm_rows
            if row.get("id") and float(row.get("similarity") or 0.0) >= _TRGM_HIGH_CONFIDENCE_SIMILARITY
        ),
        key=lambda row_id: _apply_ranking_weights(
            float(rows_by_id[row_id].get("similarity") or 0.0), rows_by_id[row_id]
        ),
        reverse=True,
    )
    remaining_ids = sorted(
        (row_id for row_id in scores if row_id not in high_confidence_ids),
        key=lambda row_id: _apply_ranking_weights(scores[row_id], rows_by_id[row_id]),
        reverse=True,
    )
    ordered_ids = [*dict.fromkeys(high_confidence_ids), *remaining_ids]
    return [rows_by_id[row_id] for row_id in ordered_ids[:limit]]


async def search_relevant_memories(
    query: str,
    user_id: str,
    threshold: float = 0.7,
    limit: int = 5,
    *,
    jwt: str | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search (Phase B1): pgvector semantic similarity merged with
    pg_trgm keyword/fuzzy matching via Reciprocal Rank Fusion. Vector search
    alone tends to miss exact proper nouns (product names, etc.) since a
    short keyword's embedding doesn't reliably land near a fact containing
    that same keyword verbatim; trigram search catches those directly and
    doesn't depend on embedding/LLM availability at all, so it also serves
    as a fallback when embedding generation itself fails.
    """
    token = jwt or await get_sigmaris_jwt()

    # Embedding generation (an LLM call) and the trigram DB query are
    # independent, so they run concurrently rather than back-to-back —
    # keeps hybrid search's added latency close to zero versus vector-only.
    embedding_result, trgm_result = await asyncio.gather(
        generate_embedding(query),
        _search_fact_memory_trgm(token, query, user_id, limit),
        return_exceptions=True,
    )

    if isinstance(embedding_result, BaseException):
        logger.exception("memory_search: embedding generation failed, continuing with trigram-only results", exc_info=embedding_result)
        embedding = []
    else:
        embedding = embedding_result

    if isinstance(trgm_result, BaseException):
        logger.exception("memory_search: trigram search failed, continuing with vector-only results", exc_info=trgm_result)
        trgm_rows = []
    else:
        trgm_rows = trgm_result

    vector_rows: list[dict[str, Any]] = []
    if embedding:
        try:
            vector_rows = await _search_fact_memory_vector(token, embedding, user_id, threshold, limit)
        except Exception:
            logger.exception("memory_search: vector search failed, continuing with trigram-only results")

    if not vector_rows and not trgm_rows:
        return []

    merged = _merge_hybrid_results(vector_rows, trgm_rows, limit=limit)
    logger.info(
        "memory_search: hybrid merge vector_hits=%d trgm_hits=%d merged=%d sources=%s",
        len(vector_rows),
        len(trgm_rows),
        len(merged),
        [row.get("match_source") for row in merged],
    )
    return merged


async def update_fact_embeddings(
    user_id: str,
    *,
    jwt: str | None = None,
) -> dict[str, int]:
    token = jwt or await get_sigmaris_jwt()
    current_user = await get_current_user(token)
    if current_user.get("id") != user_id:
        raise RuntimeError("JWT user does not match requested user_id.")

    updated = 0
    errors = 0

    while True:
        rows = await rest_select(
            token,
            "user_fact_items",
            {
                "select": "id,category,key,value,notes",
                "user_id": f"eq.{user_id}",
                "embedding": "is.null",
                "is_deleted": "eq.false",
                "is_stale": "eq.false",
                "order": "updated_at.asc",
                "limit": str(EMBED_BATCH_SIZE),
            },
        )
        items = rows if isinstance(rows, list) else []
        if not items:
            break

        batch_updated = 0
        for item in items:
            try:
                text = _fact_embedding_text(item)
                embedding = await generate_embedding(text)
                if not embedding:
                    continue
                await rest_update(
                    token,
                    "user_fact_items",
                    {"embedding": _vector_literal(embedding)},
                    {"id": f"eq.{item['id']}", "user_id": f"eq.{user_id}"},
                )
                updated += 1
                batch_updated += 1
            except Exception:
                errors += 1
                logger.exception("memory_search: failed to update embedding fact_id=%s", item.get("id"))

        if len(items) < EMBED_BATCH_SIZE or batch_updated == 0:
            break

    return {"updated": updated, "errors": errors}
