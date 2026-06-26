from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.services.self_model import get_self_model
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

# ─── Event types ──────────────────────────────────────────────────────────────

_EVENT_RESEARCH_DUE = "research_due"
_EVENT_SELF_REFLECT_DUE = "self_reflect_due"
_EVENT_X_MENTION_PENDING = "x_mention_pending"


@dataclass
class HeartbeatEvent:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"HeartbeatEvent({self.event_type!r}, {self.payload})"


# ─── Checker ──────────────────────────────────────────────────────────────────

class HeartbeatChecker:
    """Lightweight condition checker that never calls an LLM.

    Each check uses an in-process cooldown to avoid hammering external APIs or
    triggering the same LLM job multiple times within the same day.  Cooldown
    state resets on process restart — that is intentional (safe default: check
    again after restart).
    """

    # Cooldowns (seconds)
    _RESEARCH_COOLDOWN = 4 * 60 * 60     # 4 hours — research is a once-daily job
    _REFLECT_COOLDOWN = 60 * 60          # 1 hour  — avoid hammering self-reflect
    _X_MENTION_COOLDOWN = 15 * 60        # 15 min  — X API rate limits

    def __init__(self) -> None:
        self._last_triggered: dict[str, float] = {}
        self._x_user_id: str | None = None
        self._x_last_mention_time: str | None = None

    def _cooldown_ok(self, key: str, secs: int) -> bool:
        return time.monotonic() - self._last_triggered.get(key, 0.0) >= secs

    def _mark(self, key: str) -> None:
        self._last_triggered[key] = time.monotonic()

    # ── Public entry point ────────────────────────────────────────────────────

    async def check(self) -> list[HeartbeatEvent]:
        """Run all lightweight checks and return a list of pending events.

        This method must NOT call any LLM. The caller (heartbeat_tick) handles
        dispatching to services that may use LLMs.
        """
        tasks = [
            self._check_research_due(),
            self._check_self_reflect_due(),
        ]
        if settings.x_enabled and self._cooldown_ok("x_mention", self._X_MENTION_COOLDOWN):
            tasks.append(self._check_x_mentions())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        events: list[HeartbeatEvent] = []
        for res in results:
            if isinstance(res, HeartbeatEvent):
                events.append(res)
            elif isinstance(res, list):
                events.extend(res)
            elif isinstance(res, Exception):
                logger.warning("heartbeat: check raised: %s", res)

        if events:
            logger.info("heartbeat: %d event(s): %s", len(events), [e.event_type for e in events])
        return events

    # ── Individual checks (no LLM) ────────────────────────────────────────────

    async def _check_research_due(self) -> HeartbeatEvent | None:
        if not settings.research_enabled:
            return None
        if not self._cooldown_ok("research", self._RESEARCH_COOLDOWN):
            return None
        if not settings.supabase_service_role_key:
            return None

        try:
            base_url, _ = _require_supabase_config()
            client = await _get_client()
            svc_key = settings.supabase_service_role_key
            today_start = (
                datetime.now(timezone.utc)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
            )
            r = await client.get(
                f"{base_url}/rest/v1/research_items",
                headers={"apikey": svc_key, "Authorization": f"Bearer {svc_key}"},
                params={"select": "id", "created_at": f"gte.{today_start}", "limit": "1"},
            )
            if r.is_error:
                return None
            if r.json():
                return None  # research already done today
        except Exception:
            logger.warning("heartbeat: research_due check failed", exc_info=True)
            return None

        self._mark("research")
        return HeartbeatEvent(event_type=_EVENT_RESEARCH_DUE)

    async def _check_self_reflect_due(self) -> HeartbeatEvent | None:
        if not self._cooldown_ok("self_reflect", self._REFLECT_COOLDOWN):
            return None

        try:
            model = await get_self_model()
        except Exception:
            logger.warning("heartbeat: self_model fetch failed", exc_info=True)
            return None

        if not model:
            return None  # no model yet — nothing to reflect on

        last_reflected = model.get("last_reflected_at")
        if not last_reflected:
            self._mark("self_reflect")
            return HeartbeatEvent(
                event_type=_EVENT_SELF_REFLECT_DUE,
                payload={"reason": "never_reflected"},
            )

        try:
            dt = datetime.fromisoformat(last_reflected.replace("Z", "+00:00"))
        except ValueError:
            return None

        hours_elapsed = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if hours_elapsed >= 24:
            self._mark("self_reflect")
            return HeartbeatEvent(
                event_type=_EVENT_SELF_REFLECT_DUE,
                payload={"hours_since": int(hours_elapsed)},
            )
        return None

    async def _check_x_mentions(self) -> list[HeartbeatEvent]:
        """Check X (Twitter) API for new mentions since the last check.

        Requires read-access credentials (same credentials as posting).
        The X API v2 mentions timeline is rate-limited; this is gated by
        _X_MENTION_COOLDOWN (15 min) to stay well within limits.
        """
        if not all([
            settings.x_api_key,
            settings.x_api_secret,
            settings.x_access_token,
            settings.x_access_token_secret,
        ]):
            return []

        # Import OAuth helper from x_publisher to avoid duplication
        from app.services.x_publisher import _build_oauth_header

        api_key = settings.x_api_key
        api_secret = settings.x_api_secret
        access_token = settings.x_access_token
        access_token_secret = settings.x_access_token_secret

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                # Resolve user ID once; cached for the process lifetime
                if self._x_user_id is None:
                    me_url = "https://api.twitter.com/2/users/me"
                    auth = _build_oauth_header(
                        "GET", me_url, {},
                        api_key=api_key, api_secret=api_secret,
                        access_token=access_token, access_token_secret=access_token_secret,
                    )
                    r = await client.get(me_url, headers={"Authorization": auth})
                    if r.is_error:
                        logger.warning("heartbeat: x_mention /users/me HTTP %s", r.status_code)
                        return []
                    self._x_user_id = (r.json().get("data") or {}).get("id")
                    if not self._x_user_id:
                        return []

                # Fetch recent mentions
                mentions_url = f"https://api.twitter.com/2/users/{self._x_user_id}/mentions"
                query: dict[str, str] = {"max_results": "5"}
                if self._x_last_mention_time:
                    query["start_time"] = self._x_last_mention_time

                auth = _build_oauth_header(
                    "GET", mentions_url, query,
                    api_key=api_key, api_secret=api_secret,
                    access_token=access_token, access_token_secret=access_token_secret,
                )
                r = await client.get(mentions_url, headers={"Authorization": auth}, params=query)

                self._mark("x_mention")
                self._x_last_mention_time = (
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                )

                if r.is_error:
                    logger.warning("heartbeat: x_mention timeline HTTP %s", r.status_code)
                    return []

                mentions = (r.json().get("data") or [])
                if not mentions:
                    return []

                return [HeartbeatEvent(
                    event_type=_EVENT_X_MENTION_PENDING,
                    payload={"count": len(mentions), "ids": [m.get("id") for m in mentions]},
                )]
        except Exception:
            logger.warning("heartbeat: x_mention check raised", exc_info=True)
            return []


# ─── Module-level singleton ───────────────────────────────────────────────────

_checker: HeartbeatChecker | None = None


def _get_checker() -> HeartbeatChecker:
    global _checker
    if _checker is None:
        _checker = HeartbeatChecker()
    return _checker


# ─── Dispatcher ───────────────────────────────────────────────────────────────

async def _dispatch(event: HeartbeatEvent) -> None:
    """Dispatch a heartbeat event to the appropriate service.

    LLM calls happen here (inside services), never in the checker above.
    """
    if event.event_type == _EVENT_RESEARCH_DUE:
        from app.services.research_agent import run_research
        result = await run_research()
        logger.info("heartbeat: research dispatched — %s", result)

    elif event.event_type == _EVENT_SELF_REFLECT_DUE:
        from app.services.self_model import reflect
        result = await reflect()
        logger.info("heartbeat: self-reflect dispatched — %s", result)

    elif event.event_type == _EVENT_X_MENTION_PENDING:
        # Auto-reply pipeline is future work; log pending mentions for now.
        logger.info(
            "heartbeat: %d X mention(s) pending — manual review needed: ids=%s",
            event.payload.get("count", 0),
            event.payload.get("ids", []),
        )


# ─── Main tick ────────────────────────────────────────────────────────────────

async def heartbeat_tick() -> None:
    """Called by the scheduler every minute.

    1. Run lightweight checks (no LLM).
    2. Dispatch events to services (may use LLM) — each wrapped in try/except.
    """
    checker = _get_checker()
    try:
        events = await checker.check()
    except Exception:
        logger.exception("heartbeat: check() raised unexpectedly")
        return

    for event in events:
        try:
            await _dispatch(event)
        except Exception:
            logger.exception("heartbeat: dispatch failed for event=%s", event.event_type)
