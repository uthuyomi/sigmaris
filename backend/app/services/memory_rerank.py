from __future__ import annotations

# Phase B10: listwise LLM-based second-stage re-ranking.
#
# Chosen over a true cross-encoder model (Option A) after investigation —
# see phase_b10_report.md section 1 for the full writeup. In short: Ollama
# exposes no rerank/cross-encoder endpoint (only /api/chat, /api/generate,
# /api/embeddings), so Option A would mean adding sentence-transformers/
# torch as new backend dependencies (backend/pyproject.toml currently has
# zero ML libraries of its own — every existing "LLM" call in this codebase
# goes through Ollama's or OpenAI's HTTP API, never an in-process model)
# and downloading + hosting a model persistently. Whether that combination
# actually runs at acceptable speed on the target GTX 1660 server cannot be
# verified from this session (no SSH/server access, a standing constraint
# throughout this project). A single listwise LLM call reuses the exact
# same OpenAI-call machinery every other B-phase already depends on, with
# none of that unverifiable operational risk — the user confirmed this
# choice explicitly before implementation began (see phase_b10_report.md
# section 1).
#
# This is a genuinely new dedicated LLM call (unlike B8, which piggybacked
# on B7's existing call) — there was no way to fold "rerank these already-
# retrieved candidates" into a call that necessarily runs *before* those
# candidates exist. The task's own instructions acknowledged this as the
# expected outcome for Option B, as long as candidates are batched into one
# listwise call rather than one call per candidate (which would reintroduce
# the exact per-candidate-call-count cost problem B7 was designed to avoid).

import json
import logging
from typing import Any

from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_search import _RRF_K, _apply_ranking_weights

logger = logging.getLogger(__name__)

_RERANK_SYSTEM = (
    "あなたはシグマリスの記憶検索の再順位付けシステムです。ユーザーの質問に対し"
    "て、与えられた候補の記憶を関連性が高い順に並べ替えてください。関連性が低い"
    "候補は後ろに置いてください。必ず有効なJSONのみを返してください。"
)

_RERANK_PROMPT = """ユーザーの質問:
{query}

候補(番号: カテゴリ/キー: 内容):
{candidates_text}

---
これらの候補を、ユーザーの質問との関連性が高い順に並べ替えてください。
以下のJSON形式で、番号のリストのみを返してください(関連性が高い順、全ての番号
を過不足なく1回ずつ含めること):
{{"ranked_indices": [3, 1, 4, 2]}}"""


def _format_candidates(candidates: list[dict[str, Any]]) -> str:
    lines = []
    for i, row in enumerate(candidates, start=1):
        category = row.get("category") or ""
        key = row.get("fact_key") or row.get("key") or ""
        value = str(row.get("value") or "")[:300]
        lines.append(f"{i}: {category}/{key}: {value}")
    return "\n".join(lines)


async def rerank_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    time_sensitive_query: bool = False,
) -> list[dict[str, Any]]:
    """Listwise-rerank `candidates` (already ordered by the existing
    B17/B13/B8-weighted hybrid search) against `query` via a single LLM
    call, returning up to `limit` rows.

    Skips the LLM call entirely when there's nothing meaningful to
    reorder (candidates already fit within limit) — reranking a pool
    that's already going to be returned in full adds cost without any
    possible benefit (requirement 2: minimize added latency/cost).

    Falls back to the pre-rerank (already B17/B13/B8-weighted) order,
    truncated to limit, on any failure — reranking is strictly an
    enhancement layered on top of an already-reasonable ranking, never a
    required step the rest of the pipeline depends on.
    """
    if len(candidates) <= limit:
        return candidates[:limit]

    cleaned_query = query.strip()
    if not cleaned_query:
        return candidates[:limit]

    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.MEMORY_RERANK,
            [
                {"role": "system", "content": _RERANK_SYSTEM},
                {"role": "user", "content": _RERANK_PROMPT.format(
                    query=cleaned_query,
                    candidates_text=_format_candidates(candidates),
                )},
            ],
            temperature=0.0,
            max_tokens=500,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return candidates[:limit]

        raw_indices = parsed.get("ranked_indices")
        if not isinstance(raw_indices, list):
            return candidates[:limit]

        # Only trust indices that are valid, in-range, not-yet-seen
        # integers — never take LLM-generated positions at face value
        # (same defensive pattern as B2/B7's LLM-generated-id verification).
        valid_positions = range(1, len(candidates) + 1)
        seen: set[int] = set()
        ordered_positions: list[int] = []
        for idx in raw_indices:
            if isinstance(idx, int) and idx in valid_positions and idx not in seen:
                ordered_positions.append(idx)
                seen.add(idx)
        # Append any candidates the LLM omitted, preserving their original
        # (weighted) relative order — a malformed/incomplete response must
        # never silently drop a candidate from consideration.
        for pos in valid_positions:
            if pos not in seen:
                ordered_positions.append(pos)

        reordered = [candidates[pos - 1] for pos in ordered_positions]
    except Exception:
        logger.exception("memory_rerank: rerank_candidates failed, falling back to pre-rerank order")
        return candidates[:limit]

    # Phase B10 composition (see phase_b10_report.md section 4 for the full
    # rationale): convert the LLM's judged rank position into an RRF-style
    # score (same _RRF_K reuse as B7's N-list sub-query merge), then apply
    # the *same* B17/B13/B8 ranking weights this candidate already carries
    # — rather than asking the LLM to reason about those numeric signals
    # itself. None of the B-group's weighting features have ever delegated
    # numeric-weight reasoning to an LLM (B17/B13/B8 all use deterministic
    # multiplication precisely because LLMs are unreliable at correctly
    # using precise numeric weights passed as text) — this stays consistent
    # with that established design rather than introducing a new, harder-
    # to-verify way of blending signals.
    scored = [
        (
            _apply_ranking_weights(
                1.0 / (_RRF_K + rank), row, time_sensitive_query=time_sensitive_query
            ),
            row,
        )
        for rank, row in enumerate(reordered, start=1)
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _, row in scored[:limit]]
