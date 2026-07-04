from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_validator import get_confirmation_candidates
from app.services.user_fact_data import get_null_fields, upsert_fact_item

logger = logging.getLogger(__name__)

# In-process cooldown: key → last_asked unix timestamp
# Resets on restart; acceptable since cooldown is only 2 days.
_asked_cache: dict[str, float] = {}

_COOLDOWN_SECONDS = 2 * 24 * 60 * 60  # 48 hours

# Phase B3: at most one *pending* re-confirmation per thread — a fresh
# confirmation question always replaces whatever was pending before,
# rather than queuing. If the user never answers (changes topic, the
# thread goes quiet), the old pending entry is simply dropped and never
# reflected — deliberate: trying to match a reply arriving many turns
# later back to an old question risks misattributing an unrelated answer
# to the wrong fact. In-process only (like _asked_cache above), so it also
# resets on restart — acceptable for the same reason as the cooldown above.
_pending_confirmations: dict[str, dict[str, Any]] = {}

_SYSTEM = """あなたはシグマリス（家庭支援AI）です。
ユーザーに対して、まだ知らない情報を自然に質問します。
一つの質問のみ生成してください。"""

_PROMPT = """直近の会話:
{recent_messages}

シグマリスはユーザーの以下の情報をまだ知りません:
{field_description}

この情報を直近の会話の流れに自然につなげて、一つの質問文を生成してください。
「そういえば」または「ちなみに」で始めてください。
質問文のみを返してください（説明不要）。"""

# Phase B3: re-confirmation questions, distinct tone from _PROMPT above —
# persona.md 3章(共感→興味→質問)・4章(語尾: 〜ですね/〜かもしれません/どう
# でしょう、避ける: 〜である/〜すべき/絶対)に沿わせるため、断定を避け
# お伺いを立てる語尾を明示的に指示している。
_CONFIRM_SYSTEM = """あなたはシグマリス（家庭支援AI）です。
以前ユーザーから聞いた情報が、今も変わっていないかを自然に確認します。
一つの質問のみ生成してください。相手を問い詰めるような口調にはしないこと。"""

_CONFIRM_PROMPT = """直近の会話:
{recent_messages}

シグマリスは以前、ユーザーについて以下の情報を記録しています:
{field_description}: 「{current_value}」

この情報が今も変わっていないか、自然に確認する質問文を一つ生成してください。
「そういえば」または「ちなみに」のような、押しつけがましくない切り出しにしてください。
「〜ですかね」「〜で合ってますか」「〜のままですか」のような、断定せずお伺いを立てる
柔らかい語尾を使ってください。「〜である」「〜すべき」のような硬い言い切りは避けてくだ
さい。
質問文のみを返してください（説明不要）。"""

_REFLECT_SYSTEM = """あなたはシグマリスの記憶確認システムです。
シグマリスが以前記録した情報について確認質問をした後の、ユーザーの返答を解釈します。
必ず有効なJSONのみを返してください。"""

_REFLECT_PROMPT = """シグマリスが記録している情報:
{field_description}: 「{current_value}」

この情報について確認した質問への、ユーザーの直近の返答:
{user_reply}

---
ユーザーの返答を解釈し、以下のJSONで返してください:
{{
  "result": "confirmed または updated または unclear",
  "new_value": "内容が変わった場合の新しい内容（updatedの場合のみ。それ以外はnull）"
}}

- 返答が「今も変わらない」という趣旨(例:「はい」「変わってないです」「それで合ってます」)
  なら confirmed
- 返答が具体的に異なる新しい内容を示しているなら updated（new_valueに新しい内容を書く）
- 返答が曖昧、無関係、質問への回答になっていない場合は unclear（new_valueはnull）"""


async def get_inquiry_question(
    jwt: str,
    recent_messages: list[dict[str, str]],
    *,
    thread_id: str | None = None,
) -> str | None:
    """
    Return a natural question — either to fill one missing user fact, or
    (Phase B3) to re-confirm one low-confidence/stale/long-unconfirmed
    existing fact — or None if no suitable question is available.

    Rules:
    - At most one question per conversation turn, across *both* kinds of
      candidate combined (missing fields and re-confirmation candidates
      are pooled into a single ranked list — requirement 3: existing
      per-turn cap must not be loosened by adding a second candidate pool)
    - Same field not asked again for 48 hours (in-process cooldown)
    - Question is contextually relevant to the recent conversation

    thread_id (optional) lets a re-confirmation question register a
    pending entry that reflect_pending_confirmation() can later resolve
    once the user replies; without it the question is still asked
    normally, it just can't be followed up on automatically.
    """
    try:
        null_fields = await get_null_fields(jwt)
    except Exception:
        logger.exception("active_inquiry: get_null_fields failed")
        null_fields = []

    try:
        confirm_candidates = await get_confirmation_candidates(jwt)
    except Exception:
        logger.exception("active_inquiry: get_confirmation_candidates failed")
        confirm_candidates = []

    all_fields = [*null_fields, *confirm_candidates]
    if not all_fields:
        return None

    now = time.time()

    # Filter out fields asked in the last 48 hours
    candidates = [
        f for f in all_fields
        if _cache_key(f) not in _asked_cache
        or now - _asked_cache[_cache_key(f)] > _COOLDOWN_SECONDS
    ]

    if not candidates:
        logger.debug("active_inquiry: all candidates on cooldown")
        return None

    # Rank by relevance to recent conversation (keyword overlap) — missing
    # fields and re-confirmation candidates compete in the same ranking
    # rather than one kind having fixed priority over the other, matching
    # how missing fields were already ranked purely by relevance.
    conversation_text = " ".join(
        (m.get("content") or "") for m in recent_messages[-5:]
    ).lower()

    ranked = _rank_by_relevance(candidates, conversation_text)
    chosen = ranked[0]

    # Mark as asked before the LLM call so concurrent calls don't ask the same field
    _asked_cache[_cache_key(chosen)] = now

    recent_text = _format_recent(recent_messages)

    if chosen.get("source") == "user_fact_items_confirm":
        return await _generate_confirmation_question(chosen, recent_text, thread_id=thread_id)
    return await _generate_missing_field_question(chosen, recent_text)


async def _generate_missing_field_question(
    chosen: dict[str, Any],
    recent_text: str,
) -> str | None:
    field_desc = _describe_field(chosen)
    router = get_llm_router()
    try:
        question = await router.chat(
            TaskType.COMPLEX_REASONING,
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _PROMPT.format(
                    recent_messages=recent_text,
                    field_description=field_desc,
                )},
            ],
            temperature=0.7,
            max_tokens=100,
        )
        question = question.strip().strip("「」")
        if not question:
            return None
        logger.info("active_inquiry: generated question for %s", _cache_key(chosen))
        return question
    except Exception:
        logger.exception("active_inquiry: LLM call failed")
        # Roll back the cooldown since we didn't actually ask
        _asked_cache.pop(_cache_key(chosen), None)
        return None


async def _generate_confirmation_question(
    chosen: dict[str, Any],
    recent_text: str,
    *,
    thread_id: str | None,
) -> str | None:
    field_desc = _describe_field(chosen)
    current_value = str(chosen.get("value") or "")
    router = get_llm_router()
    try:
        question = await router.chat(
            TaskType.COMPLEX_REASONING,
            [
                {"role": "system", "content": _CONFIRM_SYSTEM},
                {"role": "user", "content": _CONFIRM_PROMPT.format(
                    recent_messages=recent_text,
                    field_description=field_desc,
                    current_value=current_value[:200],
                )},
            ],
            temperature=0.7,
            max_tokens=100,
        )
        question = question.strip().strip("「」")
        if not question:
            return None
        logger.info("active_inquiry: generated confirmation question for %s", _cache_key(chosen))
        if thread_id:
            _pending_confirmations[thread_id] = {
                "category": chosen.get("category"),
                "key": chosen.get("key"),
                "value": chosen.get("value"),
                "confidence": chosen.get("confidence"),
                "field_description": field_desc,
            }
        return question
    except Exception:
        logger.exception("active_inquiry: confirmation LLM call failed")
        _asked_cache.pop(_cache_key(chosen), None)
        return None


# Phase B3: reconfirming an existing value, or accepting an explicitly
# updated one, is the same "明言" tier memory_extractor.py's own extraction
# prompt already assigns 0.9 confidence to — reusing that number keeps the
# scale consistent rather than inventing a new one for this one path.
_CONFIRM_REFRESH_CONFIDENCE = 0.9


async def reflect_pending_confirmation(
    *,
    thread_id: str | None,
    turn_messages: list[dict[str, str]],
    jwt: str,
) -> None:
    """Fire-and-forget: if this thread has a pending re-confirmation
    question (set by _generate_confirmation_question above), interpret the
    user's latest reply and update user_fact_items accordingly —
    "confirmed" refreshes confidence/freshness without changing the value,
    "updated" writes the new value the user gave, "unclear" leaves the
    fact untouched. Consumes the pending entry either way (one-shot; see
    _pending_confirmations' module docstring for why this never queues).
    """
    if not thread_id:
        return
    pending = _pending_confirmations.pop(thread_id, None)
    if not pending:
        return

    user_reply = _latest_user_text(turn_messages)
    if not user_reply:
        return

    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.ROUTING,
            [
                {"role": "system", "content": _REFLECT_SYSTEM},
                {"role": "user", "content": _REFLECT_PROMPT.format(
                    field_description=pending["field_description"],
                    current_value=str(pending.get("value") or "")[:200],
                    user_reply=user_reply[:500],
                )},
            ],
            temperature=0.1,
            max_tokens=200,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return
        result = parsed.get("result")

        category = pending.get("category")
        key = pending.get("key")
        if not category or not key:
            return

        if result == "updated":
            new_value = parsed.get("new_value")
            if not isinstance(new_value, str) or not new_value.strip():
                return
            await upsert_fact_item(
                jwt,
                category=category,
                key=key,
                value=new_value.strip(),
                confidence=_CONFIRM_REFRESH_CONFIDENCE,
                source="chat",
                reason="ユーザーが確認質問に回答し内容が更新された",
                thread_id=thread_id,
            )
            logger.info("active_inquiry: confirmation reply updated %s/%s", category, key)
        elif result == "confirmed":
            refreshed_confidence = max(
                _CONFIRM_REFRESH_CONFIDENCE, float(pending.get("confidence") or 0.0)
            )
            await upsert_fact_item(
                jwt,
                category=category,
                key=key,
                value=str(pending.get("value") or ""),
                confidence=refreshed_confidence,
                source="chat",
                reason="ユーザーが確認質問に回答し変更なしと確認された",
                thread_id=thread_id,
            )
            logger.info("active_inquiry: confirmation reply confirmed %s/%s", category, key)
        # "unclear" (or any other value): leave the fact untouched.
    except Exception:
        logger.exception(
            "active_inquiry: failed to reflect pending confirmation for thread=%s", thread_id
        )


def _latest_user_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _cache_key(field: dict[str, str]) -> str:
    source = field.get("source", "")
    if source == "user_fact_profile":
        return f"profile:{field.get('key', '')}"
    if source == "user_fact_items_confirm":
        return f"confirm:{field.get('category', '')}:{field.get('key', '')}"
    return f"fact:{field.get('category', '')}:{field.get('key', '')}"


def _describe_field(field: dict[str, str]) -> str:
    source = field.get("source", "")
    key = field.get("key", "")
    if source == "user_fact_profile":
        return _PROFILE_FIELD_LABELS.get(key, key)
    category = field.get("category", "")
    return f"{_CATEGORY_LABELS.get(category, category)}: {key}"


def _rank_by_relevance(
    candidates: list[dict[str, str]],
    conversation_text: str,
) -> list[dict[str, str]]:
    """Simple keyword overlap ranking — no LLM needed."""

    def score(field: dict[str, str]) -> int:
        key = (field.get("key") or "").lower()
        label = _describe_field(field).lower()
        count = 0
        for word in key.split("_") + label.split():
            if len(word) > 1 and word in conversation_text:
                count += 1
        return count

    return sorted(candidates, key=score, reverse=True)


def _format_recent(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for m in messages[-6:]:
        role = "ユーザー" if m.get("role") == "user" else "シグマリス"
        content = (m.get("content") or "").strip()[:200]
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "（会話なし）"


_PROFILE_FIELD_LABELS: dict[str, str] = {
    "name":                  "お名前",
    "birthdate":             "生年月日",
    "prefecture":            "お住まいの都道府県",
    "city":                  "お住まいの市区町村",
    "address_detail":        "住所（番地・部屋番号）",
    "email":                 "メールアドレス",
    "occupation":            "ご職業",
    "income_range":          "おおよその収入帯",
    "lifestyle_notes":       "生活スタイルのメモ",
    "devices":               "使用デバイス",
    "preferences":           "好み・嗜好",
    "goals":                 "目標",
    "values":                "価値観",
    "communication_settings": "コミュニケーション設定",
}

_CATEGORY_LABELS: dict[str, str] = {
    "profile":       "プロフィール",
    "health":        "健康",
    "lifestyle":     "ライフスタイル",
    "environment":   "環境",
    "devices":       "デバイス",
    "preferences":   "好み",
    "relationships": "人間関係",
    "finance":       "家計",
    "goals":         "目標",
}
