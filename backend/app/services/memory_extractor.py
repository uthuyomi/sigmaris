from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_search import search_relevant_memories
from app.services.supabase_rest import get_current_user
from app.services.user_fact_data import get_fact_items, upsert_fact_item

logger = logging.getLogger(__name__)

# Must match user_fact_items_category_check in the DB migration.
_VALID_CATEGORIES = frozenset({
    "profile", "health", "lifestyle", "environment",
    "devices", "preferences", "relationships", "finance", "goals",
})

# Temporal layer Step 1 (docs/sigmaris/temporal_layer_report.md): must match
# the memory_kind CHECK constraint added by
# 202607220045_temporal_memory_layer.sql. A fact with no memory_kind (LLM
# omitted it, or returned something outside this set) is left
# unclassified (None) rather than rejected outright — extraction must not
# start failing facts over a new, optional classification.
_VALID_MEMORY_KINDS = frozenset({"event", "state", "trait"})

# Deliberately a small fixed set of common Japanese relative-date phrases,
# not a general natural-language time parser (explicit task constraint —
# "過度に複雑な自然言語時間解析は行わないこと"). Used only to estimate
# valid_from for memory_kind='state' facts; first match wins. If nothing
# matches, valid_from is left unset and upsert_fact_item()'s RPC defaults it
# to "now" — the task's own explicitly-sanctioned fallback ("会話から推定
# できない場合はcreated_atと同じ値でよい").
_RELATIVE_DATE_PHRASES: list[tuple[str, int]] = [
    ("一昨日", -2),
    ("おととい", -2),
    ("昨日", -1),
    ("今日", 0),
    ("本日", 0),
    ("先週", -7),
    ("来週", 7),
    ("今週", 0),
    ("先月", -30),
    ("来月", 30),
    ("今月", 0),
]

# How many existing facts (Phase B1 hybrid search, ranked by relevance to the
# latest user turn) to show the extraction LLM as "already-recorded" context.
# See docs/sigmaris/bug_inventory.md 2.2 for why this exists: previously the
# extraction prompt showed the LLM *no* existing facts at all, so it invented
# category/key naming fresh every turn — the same real-world fact could land
# under preferences/favorite_color one turn and lifestyle/color_preference
# the next, silently fragmenting into separate rows that the DB's exact-match
# (category, key) UNIQUE constraint can never catch. 8 is a deliberately
# generous recall-over-precision choice: showing a few irrelevant existing
# facts costs nothing (the LLM is told to ignore ones that don't match), but
# missing a genuine duplicate candidate defeats the purpose of this fix.
_EXISTING_FACTS_SEARCH_LIMIT = 8

_SYSTEM = """あなたは会話から事実を抽出するAIです。
ユーザーの会話から記憶すべき事実を抽出します。
必ず有効なJSONのみを返してください。"""

_PROMPT = """以下の会話から、ユーザーについての記憶すべき事実を抽出してください。

categoryは以下の9つのみ使用可能。それ以外は使わないこと:
- profile: 個人情報・氏名・職業・住所
- health: 健康状態・医療・身体
- lifestyle: 習慣・ルーティン・生活スタイル
- environment: 居住環境・場所
- devices: 使用デバイス・所有機器
- preferences: 好み・嫌い・趣味
- relationships: 人間関係・家族・友人
- finance: 収入・支出・財務
- goals: 目標・希望・将来計画

確信度の基準:
- 0.9: 明言（「私は〜が好き」「〜を持っている」等）
- 0.6: 会話から強く示唆される
- 0.4: 推測・間接的示唆

memory_kindは必ず次の3種類のいずれか一つとし、自由記述は禁止します:
- event: 一時的な出来事（例:「今日AdFlow AIの実装で詰まった」「先週旅行に
  行った」）。今は事実でも、時間が経つとともに古い情報になっていくもの
- state: 現在の状態、常に最新の1つだけが正である情報（例:「Phase Bは完了
  している」「今は札幌に住んでいる」）。新しい情報が来たら古い情報を置き
  換えるべきもの
- trait: 判断傾向・好み（例:「スピード重視で判断する」「猫が好き」）。継
  続的な性格・嗜好を表すもの

## 既に記録されている関連事実（参考。今回の会話に関連度が高い順）
{existing_facts_context}

**重要:** 上記の既存事実と実質的に同じ内容（表現が違うだけの言い換えを含
む）を新たに抽出する場合は、絶対に新しいcategory/keyを作らず、既存と全く
同じcategory・keyをそのまま使ってください。新しいcategory/keyを作ってよい
のは、既存のどれとも異なる、本当に新しい情報の場合だけです。

## 会話
{conversation}

JSON形式で返してください:
{{
  "facts": [
    {{
      "category": "カテゴリ名",
      "key": "snake_case_key",
      "value": "事実の内容",
      "confidence": 0.9,
      "memory_kind": "event | state | trait のいずれか一つ",
      "reason": "抽出理由（1文）"
    }}
  ]
}}
事実がなければ facts は空リスト。keyは英語のsnake_case。"""


async def extract_from_conversation(
    messages: list[dict[str, str]],
    jwt: str,
    *,
    thread_id: str | None = None,
    invocation_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract facts from a conversation and upsert them into user_fact_items.

    Runs as a background task — never raises; returns [] on any failure.
    Skips facts where an existing fact already has higher confidence.

    thread_id/invocation_id (Phase B4 provenance) record which conversation
    turn a newly-created fact originated from; optional so existing callers
    that don't have this context keep working unchanged.

    user_id is likewise optional: callers that already have it in scope
    (e.g. orchestrator/service.py's _extract_facts_bg) should pass it to
    skip a redundant get_current_user() round-trip; callers that don't
    (e.g. bench_pipeline.py's isolated benchmark ingestion) can omit it and
    it will be derived from jwt internally.
    """
    if not messages:
        return []

    conversation = _format_conversation(messages)
    if not conversation.strip():
        return []

    existing_facts_context = await _build_existing_facts_context(
        messages, jwt, user_id=user_id
    )

    router = get_llm_router()
    logger.info("memory_extractor: task=MEMORY_EXTRACTION items=%d", len(messages))
    try:
        raw = await router.chat(
            TaskType.MEMORY_EXTRACTION,
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _PROMPT.format(
                    conversation=conversation,
                    existing_facts_context=existing_facts_context,
                )},
            ],
            temperature=0.1,
            max_tokens=1024,
            json_mode=True,
        )
    except Exception:
        logger.exception("memory_extractor: LLM call failed")
        return []

    try:
        parsed = json.loads(raw)
        facts: list[dict] = parsed.get("facts", [])
    except (json.JSONDecodeError, AttributeError):
        logger.warning("memory_extractor: invalid JSON — %s", raw[:200])
        return []

    if not facts:
        return []

    try:
        existing = await get_fact_items(jwt)
    except Exception:
        existing = []

    confidence_map: dict[tuple[str, str], float] = {
        (item["category"], item["key"]): float(item.get("confidence", 0.0))
        for item in existing
        if isinstance(item.get("category"), str) and isinstance(item.get("key"), str)
    }

    upserted: list[dict[str, Any]] = []
    skipped_invalid = 0
    for fact in facts:
        if not _is_valid(fact):
            continue

        cat = str(fact["category"]).strip()
        key = str(fact["key"]).strip()
        new_conf = float(fact.get("confidence", 0.5))
        memory_kind = fact.get("memory_kind")
        memory_kind = memory_kind if memory_kind in _VALID_MEMORY_KINDS else None

        if cat not in _VALID_CATEGORIES:
            logger.debug("memory_extractor: skip invalid category '%s' (key=%s)", cat, key)
            skipped_invalid += 1
            continue

        existing_conf = confidence_map.get((cat, key), 0.0)
        # For memory_kind='state', a lower-confidence *contradiction* must
        # still reach upsert_fact_item() so its supersede branch can run —
        # this confidence-skip predates the temporal layer and was designed
        # for "don't let a shakier restatement downgrade a solid fact", not
        # for "block a real update just because it happened to be phrased
        # less certainly". event/trait/unclassified keep the original
        # behavior unchanged.
        if memory_kind != "state" and existing_conf > new_conf:
            logger.debug(
                "memory_extractor: skip %s/%s (existing=%.1f > new=%.1f)",
                cat, key, existing_conf, new_conf,
            )
            continue

        valid_from = _estimate_valid_from(conversation) if memory_kind == "state" else None

        try:
            result = await upsert_fact_item(
                jwt,
                category=cat,
                key=key,
                value=str(fact.get("value", "")).strip(),
                confidence=new_conf,
                source="chat",
                reason=str(fact.get("reason", ""))[:200],
                thread_id=thread_id,
                invocation_id=invocation_id,
                memory_kind=memory_kind,
                valid_from=valid_from,
            )
            upserted.append(result)
        except Exception:
            logger.exception("memory_extractor: upsert failed for %s/%s", cat, key)

    logger.info(
        "memory_extractor: task=MEMORY_EXTRACTION items=%d skipped=%d upserted=%d",
        len(facts), skipped_invalid, len(upserted),
    )
    return upserted


def _latest_user_text(messages: list[dict[str, str]]) -> str | None:
    """Most recent user-role message content, used as the search query for
    _build_existing_facts_context() — the newest turn is what's actually
    likely to contain a new (or duplicate) fact; searching on the whole
    multi-turn conversation would dilute the query across unrelated topics."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = (msg.get("content") or "").strip()
            if content:
                return content
    return None


async def _build_existing_facts_context(
    messages: list[dict[str, str]], jwt: str, *, user_id: str | None
) -> str:
    """Search existing user_fact_items (Phase B1 hybrid search) for facts
    relevant to the latest user turn, formatted for injection into _PROMPT.

    Best-effort: any failure here (search error, missing user_id) falls back
    to "no existing facts" context rather than blocking extraction — this
    mirrors extract_from_conversation()'s own never-raise contract, and a
    missed dedup opportunity is a much smaller cost than losing a turn's
    fact extraction entirely.
    """
    query = _latest_user_text(messages)
    if not query:
        return "（なし）"

    try:
        resolved_user_id = user_id
        if not resolved_user_id:
            user = await get_current_user(jwt)
            resolved_user_id = user.get("id")
        if not isinstance(resolved_user_id, str):
            return "（なし）"

        results = await search_relevant_memories(
            query, resolved_user_id, limit=_EXISTING_FACTS_SEARCH_LIMIT, jwt=jwt
        )
    except Exception:
        logger.debug("memory_extractor: existing-facts search failed, proceeding without it", exc_info=True)
        return "（なし）"

    lines = [
        f"- {row.get('category')}/{row.get('key')}: {row.get('value')}"
        for row in results
        if isinstance(row.get("category"), str) and isinstance(row.get("key"), str) and row.get("value")
    ]
    return "\n".join(lines) if lines else "（なし）"


def _estimate_valid_from(conversation: str) -> str | None:
    """Best-effort valid_from estimate for a memory_kind='state' fact, from
    a small fixed set of common Japanese relative-date phrases (see
    _RELATIVE_DATE_PHRASES) — not a general time-expression parser. Returns
    None (RPC defaults to "now") when nothing matches."""
    for phrase, offset_days in _RELATIVE_DATE_PHRASES:
        if phrase in conversation:
            return (datetime.now(UTC) + timedelta(days=offset_days)).isoformat()
    return None


def _format_conversation(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for msg in messages[-20:]:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        label = "ユーザー" if role == "user" else "シグマリス"
        lines.append(f"{label}: {content[:500]}")
    return "\n".join(lines)


def _is_valid(fact: Any) -> bool:
    if not isinstance(fact, dict):
        return False
    for field in ("category", "key", "value"):
        if not isinstance(fact.get(field), str) or not fact[field].strip():
            return False
    conf = fact.get("confidence")
    if conf is not None and not isinstance(conf, (int, float)):
        return False
    return True
