from __future__ import annotations

import json
import logging
from typing import Any

from app.services.local_llm import TaskType, get_llm_router
from app.services.user_fact_data import get_fact_items, upsert_fact_item

logger = logging.getLogger(__name__)

_SYSTEM = """あなたは会話から事実を抽出するAIです。
ユーザーの会話から記憶すべき事実を抽出します。
必ず有効なJSONのみを返してください。"""

_PROMPT = """以下の会話から、ユーザーについての記憶すべき事実を抽出してください。

対象カテゴリ:
- preference: 好み・嫌い
- habit: 習慣・ルーティン
- goal: 目標・希望
- possession: 所有物・使用デバイス
- relationship: 人間関係（家族・友人・同僚）
- event: 起きた出来事・今後の予定
- health: 健康状態
- work: 仕事・職業関連

確信度の基準:
- 0.9: 明言（「私は〜が好き」「〜を持っている」等）
- 0.6: 会話から強く示唆される
- 0.4: 推測・間接的示唆

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
      "reason": "抽出理由（1文）"
    }}
  ]
}}
事実がなければ facts は空リスト。keyは英語のsnake_case。"""


async def extract_from_conversation(
    messages: list[dict[str, str]],
    jwt: str,
) -> list[dict[str, Any]]:
    """Extract facts from a conversation and upsert them into user_fact_items.

    Runs as a background task — never raises; returns [] on any failure.
    Skips facts where an existing fact already has higher confidence.
    """
    if not messages:
        return []

    conversation = _format_conversation(messages)
    if not conversation.strip():
        return []

    router = get_llm_router()
    try:
        raw = await router.chat(
            TaskType.MEMORY_EXTRACTION,
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _PROMPT.format(conversation=conversation)},
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
    for fact in facts:
        if not _is_valid(fact):
            continue

        cat = str(fact["category"]).strip()
        key = str(fact["key"]).strip()
        new_conf = float(fact.get("confidence", 0.5))

        existing_conf = confidence_map.get((cat, key), 0.0)
        if existing_conf > new_conf:
            logger.debug(
                "memory_extractor: skip %s/%s (existing=%.1f > new=%.1f)",
                cat, key, existing_conf, new_conf,
            )
            continue

        try:
            result = await upsert_fact_item(
                jwt,
                category=cat,
                key=key,
                value=str(fact.get("value", "")).strip(),
                confidence=new_conf,
                source="chat",
                reason=str(fact.get("reason", ""))[:200],
            )
            upserted.append(result)
        except Exception:
            logger.exception("memory_extractor: upsert failed for %s/%s", cat, key)

    logger.info(
        "memory_extractor: %d facts extracted, %d upserted",
        len(facts), len(upserted),
    )
    return upserted


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
