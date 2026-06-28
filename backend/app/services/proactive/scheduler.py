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
from app.services.heartbeat import heartbeat_tick
from app.services.research_agent import run_research
from app.services.proactive.jwt_manager import get_sigmaris_jwt

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _safe(fn: Callable[[], Awaitable[ActionResult]], name: str) -> None:
    try:
        result = await fn()
        logger.info("Proactive job %s done: ok=%s notified=%s", name, result.ok, result.notified)
    except Exception:
        logger.exception("Proactive job %s raised unexpectedly", name)


async def _heartbeat() -> None:
    try:
        await heartbeat_tick()
    except Exception:
        logger.exception("Heartbeat job raised unexpectedly")


async def _research() -> None:
    try:
        result = await run_research()
        logger.info("Research job done: %s", result)
    except Exception:
        logger.exception("Research job raised unexpectedly")


async def _morning() -> None:
    await _safe(run_morning_briefing, "morning_briefing")


async def _evening() -> None:
    await _safe(run_evening_checkin, "evening_checkin")


async def _weekly() -> None:
    await _safe(run_weekly_review, "weekly_review")


async def _memory_validate() -> None:
    from app.services.memory_validator import validate_all_facts  # noqa: PLC0415
    try:
        jwt = await get_sigmaris_jwt()
        result = await validate_all_facts(jwt)
        logger.info("Memory validate job done: %s", result)
    except Exception:
        logger.exception("Memory validate job raised unexpectedly")


async def _health_data_sync() -> None:
    if not settings.health_sync_enabled:
        return
    from app.services.health_data import HealthDataCollector  # noqa: PLC0415
    from datetime import date, timedelta  # noqa: PLC0415
    try:
        jwt = await get_sigmaris_jwt()
        google_token = settings.sigmaris_google_access_token
        if not google_token:
            logger.info("health_data_sync: SIGMARIS_GOOGLE_ACCESS_TOKEN not set, skipping")
            return
        yesterday = date.today() - timedelta(days=1)
        collector = HealthDataCollector()
        summary = await collector.fetch_daily_summary(yesterday, google_token)
        stored = await collector.store_to_fact_memory(jwt, summary)
        logger.info(
            "health_data_sync: stored %d items for %s", len(stored), yesterday.isoformat()
        )
    except Exception:
        logger.exception("health_data_sync job raised unexpectedly")


async def _trend_analyze() -> None:
    from app.services.trend_analyzer import analyze_trends  # noqa: PLC0415
    try:
        jwt = await get_sigmaris_jwt()
        result = await analyze_trends(jwt)
        logger.info("Trend analyze job done: %s", result)
    except Exception:
        logger.exception("Trend analyze job raised unexpectedly")


async def _narrative_generate() -> None:
    from app.services.self_narrative import generate_narrative_chapter  # noqa: PLC0415
    try:
        chapter = await generate_narrative_chapter()
        if chapter:
            logger.info(
                "Narrative generate job done: chapter=%s title=%s",
                chapter.get("chapter"), chapter.get("title"),
            )
        else:
            logger.warning("Narrative generate job: returned None")
    except Exception:
        logger.exception("Narrative generate job raised unexpectedly")


async def _curiosity_search() -> None:
    from app.services.curiosity_engine import execute_curiosity_search  # noqa: PLC0415
    try:
        result = await execute_curiosity_search()
        logger.info("Curiosity search job done: %s", result)
    except Exception:
        logger.exception("Curiosity search job raised unexpectedly")


async def _self_interest_queries() -> None:
    from app.services.curiosity_engine import generate_self_interest_queries  # noqa: PLC0415
    try:
        result = await generate_self_interest_queries()
        logger.info("Self-interest query job done: generated=%d", len(result))
    except Exception:
        logger.exception("Self-interest query job raised unexpectedly")


async def _experience_analyze() -> None:
    from app.services.experience_layer import analyze_patterns  # noqa: PLC0415
    try:
        result = await analyze_patterns()
        logger.info("Experience analyze job done: patterns=%s", list(result.keys()) if result else None)
    except Exception:
        logger.exception("Experience analyze job raised unexpectedly")


async def _decision_analyze() -> None:
    from app.services.decision_log import analyze_decision_patterns  # noqa: PLC0415
    try:
        result = await analyze_decision_patterns()
        logger.info("Decision analyze job done: keys=%s", list(result.keys()) if result else None)
    except Exception:
        logger.exception("Decision analyze job raised unexpectedly")


def startup_scheduler() -> None:
    global _scheduler

    if not settings.proactive_enabled:
        logger.info("Proactive scheduler disabled (PROACTIVE_ENABLED=false)")
        return

    tz = settings.sigmaris_timezone
    _scheduler = AsyncIOScheduler(timezone=tz)

    _scheduler.add_job(_heartbeat,       CronTrigger(minute="*/1",                       timezone=tz), id="heartbeat",       replace_existing=True)
    _scheduler.add_job(_research,        CronTrigger(hour=7,  minute=0,                  timezone=tz), id="research",        replace_existing=True)
    _scheduler.add_job(_memory_validate, CronTrigger(hour=6,  minute=30,                 timezone=tz), id="memory_validate", replace_existing=True)
    _scheduler.add_job(_health_data_sync,CronTrigger(hour=6,  minute=45,                 timezone=tz), id="health_sync",     replace_existing=True)
    _scheduler.add_job(_trend_analyze,   CronTrigger(day_of_week="mon", hour=6, minute=0, timezone=tz), id="trend_analyze",  replace_existing=True)
    _scheduler.add_job(_morning,         CronTrigger(hour=8,  minute=0,                  timezone=tz), id="morning_briefing",replace_existing=True)
    _scheduler.add_job(_evening,         CronTrigger(hour=22, minute=0,                  timezone=tz), id="evening_checkin", replace_existing=True)
    _scheduler.add_job(_weekly,             CronTrigger(day_of_week="sun", hour=20, minute=0,  timezone=tz), id="weekly_review",      replace_existing=True)
    _scheduler.add_job(_narrative_generate, CronTrigger(day_of_week="sun", hour=5,  minute=0,  timezone=tz), id="narrative_generate", replace_existing=True)
    _scheduler.add_job(_curiosity_search,     CronTrigger(hour=6,  minute=15,                    timezone=tz), id="curiosity_search",     replace_existing=True)
    _scheduler.add_job(_experience_analyze,   CronTrigger(day_of_week="sun", hour=4,  minute=0,  timezone=tz), id="experience_analyze",   replace_existing=True)
    _scheduler.add_job(_decision_analyze,     CronTrigger(day_of_week="sun", hour=4,  minute=30, timezone=tz), id="decision_analyze",     replace_existing=True)
    _scheduler.add_job(_self_interest_queries,CronTrigger(day_of_week="sun", hour=5,  minute=30, timezone=tz), id="self_interest_queries",replace_existing=True)

    _scheduler.start()
    logger.info("Proactive scheduler started (tz=%s)", tz)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Proactive scheduler shut down")
