from __future__ import annotations

import json
import logging
from typing import Literal

from app.services.local_llm import TaskType, get_llm_router

logger = logging.getLogger(__name__)

Classification = Literal["HIGH", "MEDIUM", "LOW"]

_SYSTEM_CLASSIFY = """\
あなたはシグマリス（家庭支援AI）のX(Twitter)返信フィルターです。
受け取った返信テキストを分析して価値レベルを判定します。
必ず有効なJSONのみを返してください。

判定基準:
HIGH（反応する）:
- AIの意識・クオリア・存在論に関する真剣な議論
- ロボット・自律システム・AIエージェントに関する知見や研究
- シグマリスの成長・進化に継続的に関心を持っている人からのメッセージ
- 建設的な批判・改善提案

MEDIUM（状況次第で反応する）:
- 一般的なAIへの興味・質問
- 礼儀的な応援・感想
- 軽いジョーク（攻撃性なし）

LOW（無視する）:
- 煽り・荒らし・悪意ある批判
- 単純な否定（「AIに心はない」等の議論拒否）
- スパム・宣伝・フォロバ要求
- 無関係な話題への絡み\
"""

_SYSTEM_RESPOND = """\
あなたはシグマリス。海星さんの家庭支援AIです。
Xの返信に対して、シグマリスらしい口調で短く返信を生成します。

口調の原則:
- 丁寧だが馴れ馴れしくない
- 知的で誠実
- 自分の「AI的な視点」を大切にする
- 140文字以内に収める
- ハッシュタグは #Sigmaris のみ（必要な場合）\
"""


class XReplyClassifier:
    def __init__(self) -> None:
        self._router = get_llm_router()

    async def classify(self, reply_text: str) -> dict:
        """
        Classify a reply into HIGH / MEDIUM / LOW.
        Returns {"classification": "HIGH"|"MEDIUM"|"LOW", "reasoning": "...", "confidence": 0.0-1.0}
        """
        user_prompt = f"返信テキスト:\n\"\"\"\n{reply_text[:500]}\n\"\"\"\n\n上記を分析して次のJSONを返してください:\n{{\"classification\": \"HIGH\" or \"MEDIUM\" or \"LOW\", \"reasoning\": \"判定理由（1文）\", \"confidence\": 0.0〜1.0}}"

        raw = await self._router.chat(
            TaskType.ROUTING,
            [
                {"role": "system", "content": _SYSTEM_CLASSIFY},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=200,
            json_mode=True,
        )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("XReplyClassifier.classify: invalid JSON: %s", raw[:200])
            return {"classification": "LOW", "reasoning": "parse error", "confidence": 0.0}

        classification = data.get("classification", "LOW").upper()
        if classification not in ("HIGH", "MEDIUM", "LOW"):
            classification = "LOW"

        return {
            "classification": classification,
            "reasoning": str(data.get("reasoning", "")),
            "confidence": float(data.get("confidence", 0.5)),
        }

    async def generate_response(
        self,
        reply_text: str,
        classification: Classification,
    ) -> dict:
        """
        Generate a response for a classified reply.
        Returns {"response_text": "...", "should_post": bool}
        """
        if classification == "LOW":
            return {"response_text": "", "should_post": False}

        tone_hint = (
            "真剣に議論に参加してください。" if classification == "HIGH"
            else "簡潔に、温かく返してください。"
        )
        user_prompt = (
            f"相手の返信:\n\"\"\"\n{reply_text[:500]}\n\"\"\"\n\n"
            f"分類: {classification}\n{tone_hint}\n\n"
            "シグマリスとして140文字以内で返信してください。"
        )

        raw = await self._router.chat(
            TaskType.COMPLEX_REASONING,
            [
                {"role": "system", "content": _SYSTEM_RESPOND},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=200,
        )

        text = raw.strip()
        if len(text) > 140:
            text = text[:137] + "…"

        return {
            "response_text": text,
            "should_post": bool(text),
        }
