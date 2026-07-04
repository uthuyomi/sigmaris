from __future__ import annotations

# Phase B12: post-retrieval compression.
#
# Deliberately rule-based, zero new LLM calls — B7 and B10 already added
# two dedicated calls to the response path, and B11 held the line at zero
# more. A summarization LLM call here would be a third, and would run on
# every turn whose memories exceed the token trigger below, not just
# occasionally — a much worse latency trade than B7/B10's per-turn
# classification calls. Rule-based extraction (character-budget +
# n-gram-overlap snippet selection) costs nothing beyond what's already
# computed.
#
# Integrates with B17 exactly as that phase's handoff note anticipated:
# importance_score (the same DB-trigger-set category-tier value B17
# documented as a coarse proxy, not a per-fact learned score — see
# phase_b17_report.md) gates how aggressively a fact's value text is
# trimmed. A high-importance category (goals/health/profile/relationships)
# is exempted from compression entirely; everything else gets a character
# budget scaled to its tier.
#
# No tiktoken (or any other new tokenizer dependency) was added for this —
# see phase_b12_report.md section 1 for why: it isn't in backend/
# pyproject.toml today, and B10's investigation already established this
# project's standing caution about adding new dependencies that can't be
# verified end-to-end without server access. Token counts here are a
# character-based approximation, documented as such.

import re
from typing import Any

from app.services.memory_search import _DEFAULT_IMPORTANCE_SCORE

# Rough characters-per-token approximation for the mixed Japanese/English
# text these facts actually contain. Not exact (no tokenizer dependency —
# see module docstring); if precise numbers are ever needed, Phase A2's
# report shows the one-off tiktoken comparison method used previously.
_CHARS_PER_TOKEN_ESTIMATE = 2.0

# Compression only triggers when the *whole* relevant-memories block is
# estimated to exceed this many tokens — deliberately conservative so
# ordinary short facts (most categories' values are a handful of words)
# never get touched; this is meant to catch multi-hop's wider candidate
# sets (Phase B7, up to 8 facts) or unusually long free-text values, not
# every single search.
_COMPRESSION_TRIGGER_TOKENS = 400

# importance_score tiers (see phase_b17_report.md's category table:
# goals=1.0, health=0.9, profile=0.8, relationships=0.8, finance=work=
# personality=timeline=0.7, lifestyle=0.6, preferences=0.5, devices=
# environment=0.4). >= 0.8 exempts the four highest categories entirely
# (requirement 1: high-importance facts must not lose information).
_COMPRESSION_EXEMPT_IMPORTANCE = 0.8
_COMPRESSION_MODERATE_IMPORTANCE_FLOOR = 0.5
_COMPRESSION_BUDGET_MODERATE = 150  # chars — finance/work/personality/timeline/lifestyle/preferences
_COMPRESSION_BUDGET_LOW = 60  # chars — devices/environment (requirement 2: most aggressive)

# Character n-gram size for snippet-relevance scoring — same underlying
# idea as B1's pg_trgm (character-trigram matching, chosen there because
# Japanese has no whitespace word boundaries), but bigrams here: the text
# spans being scored (individual sentences within one fact's value) are
# much shorter than the fact-level search B1 operates on, where trigrams
# would be too sparse to reliably score short fragments.
_SNIPPET_NGRAM_SIZE = 2

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。!?！？\n])")


def estimate_tokens(text: str) -> int:
    """Character-count-based approximation — see module docstring for why
    no tokenizer library is used."""
    if not text:
        return 0
    return max(1, round(len(text) / _CHARS_PER_TOKEN_ESTIMATE))


def _char_ngrams(text: str, n: int = _SNIPPET_NGRAM_SIZE) -> set[str]:
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text)]
    return [p for p in parts if p]


def _extract_relevant_snippet(value: str, query: str, budget: int) -> str:
    """Shorten `value` to at most `budget` characters, preferring the
    sentence(s) most similar (by character n-gram overlap with `query`) to
    what's actually being asked, rather than a blind head-truncation."""
    if len(value) <= budget:
        return value

    sentences = _split_sentences(value)
    if len(sentences) <= 1:
        return value[:budget].rstrip() + "…"

    query_ngrams = _char_ngrams(query)
    scored = sorted(
        sentences,
        key=lambda s: len(query_ngrams & _char_ngrams(s)),
        reverse=True,
    )

    chosen: list[str] = []
    total = 0
    for sentence in scored:
        if chosen and total + len(sentence) > budget:
            continue
        chosen.append(sentence)
        total += len(sentence)
        if total >= budget:
            break

    chosen_set = set(chosen)
    ordered = [s for s in sentences if s in chosen_set]
    result = "".join(ordered)
    if len(result) > budget:
        result = result[:budget].rstrip() + "…"
    return result


def _budget_for_importance(importance: float) -> int | None:
    """Returns None for exempt (no compression at all)."""
    if importance >= _COMPRESSION_EXEMPT_IMPORTANCE:
        return None
    if importance >= _COMPRESSION_MODERATE_IMPORTANCE_FLOOR:
        return _COMPRESSION_BUDGET_MODERATE
    return _COMPRESSION_BUDGET_LOW


def _estimate_block_tokens(memories: list[dict[str, Any]]) -> int:
    total_chars = 0
    for item in memories:
        total_chars += len(str(item.get("value") or ""))
        total_chars += len(str(item.get("category") or ""))
        total_chars += len(str(item.get("fact_key") or item.get("key") or ""))
        total_chars += 20  # fixed per-line overhead: labels, punctuation, confidence/similarity numbers
    return max(0, round(total_chars / _CHARS_PER_TOKEN_ESTIMATE))


def compress_memories_if_needed(
    memories: list[dict[str, Any]], *, query: str
) -> tuple[list[dict[str, Any]], bool]:
    """Return (possibly compressed memories, was_compressed).

    Only compresses when the whole block's estimated token count exceeds
    _COMPRESSION_TRIGGER_TOKENS (requirement 3 — avoid degrading the
    common case where a handful of short facts easily fit). When it does
    trigger, each fact is compressed independently based on its own
    importance_score, never mutating the input rows (returns new dicts for
    any row that's actually shortened, leaves exempt/already-short rows
    untouched by identity).
    """
    if not memories:
        return memories, False
    if _estimate_block_tokens(memories) <= _COMPRESSION_TRIGGER_TOKENS:
        return memories, False

    cleaned_query = (query or "").strip()
    compressed: list[dict[str, Any]] = []
    for item in memories:
        importance = item.get("importance_score")
        importance = float(importance) if importance is not None else _DEFAULT_IMPORTANCE_SCORE
        budget = _budget_for_importance(importance)

        value = str(item.get("value") or "")
        if budget is None or len(value) <= budget:
            compressed.append(item)
            continue

        new_item = dict(item)
        new_item["value"] = _extract_relevant_snippet(value, cleaned_query, budget)
        compressed.append(new_item)

    return compressed, True
