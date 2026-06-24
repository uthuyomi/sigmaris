from __future__ import annotations

import logging
from typing import Awaitable, Callable, TypeVar

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.proactive.actions import (
    ActionResult,
    run_evening_checkin,
    run_morning_briefing,
    run_weekly_review,
)

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _safe(fn: Callable[[], Awaitable[ActionResult]], name: str) -> None:
    try:
        result = await fn()
        logger.info("Proactive job %s done: ok=%s notified=%s", name, result.ok, result.notified)
    except Exception:
        logger.exception("Proactive job %s raised unexpectedly", name)


async def _morning() -> None:
    await _safe(run_morning_briefing, "morning_briefing")


async def _evening() -> None:
    await _safe(run_evening_checkin, "evening_checkin")


async def _weekly() -> None:
    await _safe(run_weekly_review, "weekly_review")


def startup_scheduler() -> None:
    global _scheduler

    if not settings.proactive_enabled:
        logger.info("Proactive scheduler disabled (PROACTIVE_ENABLED=false)")
        return

    tz = settings.sigmaris_timezone
    _scheduler = AsyncIOScheduler(timezone=tz)

    _scheduler.add_job(_morning, CronTrigger(hour=8, minute=0, timezone=tz), id="morning_briefing", replace_existing=True)
    _scheduler.add_job(_evening, CronTrigger(hour=22, minute=0, timezone=tz), id="evening_checkin", replace_existing=True)
    _scheduler.add_job(_weekly, CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=tz), id="weekly_review", replace_existing=True)

    _scheduler.start()
    logger.info("Proactive scheduler started (tz=%s)", tz)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Proactive scheduler shut down")
