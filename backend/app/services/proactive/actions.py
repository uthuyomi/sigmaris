from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from app.services.orchestrator.service import run_orchestrator_chat
from app.services.proactive.jwt_manager import get_sigmaris_jwt
from app.services.proactive.notifier import get_notifier

logger = logging.getLogger(__name__)

_MORNING_PROMPT = (
    "おはようございます。今日の朝のブリーフィングをお願いします。"
    "今日の予定・重要タスク・未完了タスク・天気・支出状況・健康サマリーを簡潔にまとめてください。"
)
_EVENING_PROMPT = (
    "今日のチェックインをお願いします。"
    "本日完了したこと・未完了のこと・明日の準備として気をつけるべきことを簡潔にまとめてください。"
)
_WEEKLY_PROMPT = (
    "今週のレビューをお願いします。"
    "今週の達成・未達成・来週の優先事項・Sigmarisの改善点を簡潔にまとめてください。"
)


@dataclass
class ActionResult:
    action: str
    ok: bool
    notified: bool = False
    error: str | None = None
    tags: list[str] = field(default_factory=list)


async def _run_action(action_name: str, title: str, prompt: str) -> ActionResult:
    try:
        jwt = await get_sigmaris_jwt()
    except RuntimeError as exc:
        return ActionResult(action=action_name, ok=False, error=str(exc))

    thread_id = f"proactive-{action_name}-{uuid.uuid4()}"
    try:
        result = await run_orchestrator_chat(
            jwt=jwt,
            google_access_token=None,
            google_refresh_token=None,
            messages=[{"role": "user", "content": prompt}],
            thread_id=thread_id,
            request_context={
                "reason": f"proactive:{action_name}",
                "caller_agent_id": f"proactive-scheduler:{action_name}",
            },
        )
    except Exception as exc:
        logger.exception("Proactive action %s orchestrator call failed", action_name)
        return ActionResult(action=action_name, ok=False, error=str(exc))

    text = result.get("text", "")
    notifier = get_notifier()
    notified = await notifier.send(title=title, message=text[:1024])

    return ActionResult(action=action_name, ok=True, notified=notified)


# 【旧世代廃止タスク(docs/sigmaris/phase_h_report.md)での変更点】
# 旧_try_smart_x_post()(should_post_today()の固定スロット判定でX投稿を
# 直接実行していた経路)は、本タスクで削除した。X投稿は、現在は
# proactive/scheduler.py::_categorized_x_post_check()という、独立した
# 定期ジョブ(H-1の7カテゴリシステム、Executive Gate駆動)からのみ行われる
# ——朝・夕方・週次のブリーフィング/チェックイン/レビューという、この
# ファイルの本来の役割(通知の生成)からは、完全に切り離した。


async def run_morning_briefing() -> ActionResult:
    logger.info("Running morning briefing")
    return await _run_action("morning_briefing", "シグマリス 朝のブリーフィング", _MORNING_PROMPT)


async def run_evening_checkin() -> ActionResult:
    logger.info("Running evening check-in")
    return await _run_action("evening_checkin", "シグマリス 夕方チェックイン", _EVENING_PROMPT)


async def run_weekly_review() -> ActionResult:
    logger.info("Running weekly review")
    return await _run_action("weekly_review", "シグマリス 週次レビュー", _WEEKLY_PROMPT)
