from __future__ import annotations

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


async def search_relevant_memories(
    query: str,
    user_id: str,
    threshold: float = 0.7,
    limit: int = 5,
    *,
    jwt: str | None = None,
) -> list[dict[str, Any]]:
    embedding = await generate_embedding(query)
    if not embedding:
        return []

    token = jwt or await get_sigmaris_jwt()
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
