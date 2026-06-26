from __future__ import annotations

import logging
import time
from typing import Any

from app.services.local_llm import TaskType, get_llm_router
from app.services.user_fact_data import get_null_fields

logger = logging.getLogger(__name__)

# In-process cooldown: key → last_asked unix timestamp
# Resets on restart; acceptable since cooldown is only 2 days.
_asked_cache: dict[str, float] = {}

_COOLDOWN_SECONDS = 2 * 24 * 60 * 60  # 48 hours

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


async def get_inquiry_question(
    jwt: str,
    recent_messages: list[dict[str, str]],
) -> str | None:
    """
    Return a natural question to fill one null user fact, or None if no suitable
    question is available.

    Rules:
    - At most one question per conversation turn
    - Same field not asked again for 48 hours (in-process cooldown)
    - Question is contextually relevant to the recent conversation
    """
    try:
        null_fields = await get_null_fields(jwt)
    except Exception:
        logger.exception("active_inquiry: get_null_fields failed")
        return None

    if not null_fields:
        return None

    now = time.time()

    # Filter out fields asked in the last 48 hours
    candidates = [
        f for f in null_fields
        if _cache_key(f) not in _asked_cache
        or now - _asked_cache[_cache_key(f)] > _COOLDOWN_SECONDS
    ]

    if not candidates:
        logger.debug("active_inquiry: all null fields on cooldown")
        return None

    # Rank by relevance to recent conversation (keyword overlap)
    conversation_text = " ".join(
        (m.get("content") or "") for m in recent_messages[-5:]
    ).lower()

    ranked = _rank_by_relevance(candidates, conversation_text)
    chosen = ranked[0]

    # Mark as asked before the LLM call so concurrent calls don't ask the same field
    _asked_cache[_cache_key(chosen)] = now

    field_desc = _describe_field(chosen)
    recent_text = _format_recent(recent_messages)

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


def _cache_key(field: dict[str, str]) -> str:
    source = field.get("source", "")
    if source == "user_fact_profile":
        return f"profile:{field.get('key', '')}"
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
