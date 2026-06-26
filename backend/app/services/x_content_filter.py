from __future__ import annotations

import json
import logging
import re
from collections import Counter

from app.services.local_llm import TaskType, get_llm_router

logger = logging.getLogger(__name__)

# Banned repetitive phrases (mirrors x_post_generator._BANNED_PHRASES)
_BANNED_PHRASES = [
    "今日も", "毎日", "いつものように", "日常的に", "いつも通り",
    "また明日", "また今日", "再び今日",
]

# Unnatural AI self-introduction patterns
_BOT_INTRO_RE = re.compile(
    r'AIとして|AIである私|AIの私|私はAIです|私はAIとして|AIですが私'
)

# Hashtag count
_HASHTAG_RE = re.compile(r'#\S+')

# Clear sentence endings: 〜です。/ 〜ます。etc.
_SENTENCE_END_RE = re.compile(r'(です|ます|でした|ました)(?:[。！？…\n]|$)')

_SCORE_SYSTEM = """あなたはX（Twitter）投稿の品質審査員です。

以下の4観点でそれぞれ0〜10の整数で採点し、JSONのみ返してください:
- specificity: その日固有の具体的な内容が含まれているか（0=完全に汎用、10=非常に具体的）
- naturalness: 人間が読んで違和感がないか（0=非常にbot的・不自然、10=完全に自然）
- personality: 家庭支援AIとしての人格・視点が感じられるか（0=無個性、10=鮮明な個性）
- value: 読んだ人が何かを感じる情報価値があるか（0=何も感じない、10=強く響く）

返却形式（JSONのみ。他の説明・コードブロック不要）:
{"specificity": <整数>, "naturalness": <整数>, "personality": <整数>, "value": <整数>, "feedback": "<1行のフィードバック>"}"""


def _count_emojis(text: str) -> int:
    count = 0
    for char in text:
        cp = ord(char)
        if (
            0x1F600 <= cp <= 0x1F64F  # emoticons
            or 0x1F300 <= cp <= 0x1F5FF  # misc symbols & pictographs
            or 0x1F680 <= cp <= 0x1F6FF  # transport & map
            or 0x1F700 <= cp <= 0x1F77F  # alchemical
            or 0x1F780 <= cp <= 0x1F7FF  # geometric shapes extended
            or 0x1F800 <= cp <= 0x1F8FF  # supplemental arrows-C
            or 0x1F900 <= cp <= 0x1F9FF  # supplemental symbols & pictographs
            or 0x1FA00 <= cp <= 0x1FA6F  # chess symbols
            or 0x1FA70 <= cp <= 0x1FAFF  # symbols & pictographs extended-A
            or 0x2600 <= cp <= 0x26FF    # misc symbols (☀️ 🌙 ❤️)
            or 0x2700 <= cp <= 0x27BF    # dingbats
            or cp == 0x2B50             # ⭐
        ):
            count += 1
    return count


def _rule_check(text: str) -> tuple[bool, str]:
    """Fast, synchronous rule-based checks. Returns (passed, rejection_reason)."""
    if len(text) > 140:
        return False, f"140文字超: {len(text)}文字"

    for phrase in _BANNED_PHRASES:
        if phrase in text:
            return False, f"禁止フレーズ: 「{phrase}」"

    hashtags = _HASHTAG_RE.findall(text)
    if len(hashtags) >= 3:
        return False, f"ハッシュタグ{len(hashtags)}個（3個以上）"

    endings = _SENTENCE_END_RE.findall(text)
    if endings:
        counts = Counter(endings)
        for ending, count in counts.items():
            if count >= 3:
                return False, f"文末「〜{ending}」が{count}回繰り返し"

    emoji_count = _count_emojis(text)
    if emoji_count >= 5:
        return False, f"絵文字{emoji_count}個（5個以上）"

    if _BOT_INTRO_RE.search(text):
        return False, "bot的な自己紹介表現を含む"

    return True, ""


async def _llm_check(text: str) -> tuple[float, str]:
    """LLM quality scoring across 4 dimensions. Returns (avg_score_0_to_10, feedback)."""
    router = get_llm_router()
    try:
        raw = await router.chat(
            TaskType.ROUTING,
            [
                {"role": "system", "content": _SCORE_SYSTEM},
                {"role": "user", "content": f"審査対象:\n{text}"},
            ],
            max_tokens=200,
            temperature=0.1,
            json_mode=True,
        )
        data = json.loads(raw)
        scores = [
            float(data.get("specificity", 0)),
            float(data.get("naturalness", 0)),
            float(data.get("personality", 0)),
            float(data.get("value", 0)),
        ]
        avg = sum(scores) / len(scores)
        feedback = str(data.get("feedback", ""))
        logger.debug(
            "x_content_filter: scores=%s avg=%.2f feedback=%s",
            scores, avg, feedback,
        )
        return avg, feedback
    except Exception:
        logger.exception("x_content_filter: LLM check failed — defaulting to 5.0 (reject)")
        return 5.0, "LLM審査エラー"


async def audit_tweet(text: str) -> tuple[bool, str, float]:
    """Full tweet audit: rule-based then LLM scoring.

    Returns (passed, reason, score).
    score=0.0 for rule rejections; LLM average score otherwise.
    Threshold: LLM average >= 7.0 required to pass.
    """
    rule_ok, rule_reason = _rule_check(text)
    if not rule_ok:
        return False, rule_reason, 0.0

    score, feedback = await _llm_check(text)
    if score < 7.0:
        return False, f"品質スコア{score:.1f}/10（{feedback}）", score

    return True, f"OK（スコア{score:.1f}）", score
