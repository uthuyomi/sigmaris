from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


class BaseNotifier(ABC):
    @abstractmethod
    async def send(self, title: str, message: str) -> bool: ...


class PushoverNotifier(BaseNotifier):
    def __init__(self, app_token: str, user_key: str) -> None:
        self._app_token = app_token
        self._user_key = user_key

    async def send(self, title: str, message: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    _PUSHOVER_URL,
                    data={
                        "token": self._app_token,
                        "user": self._user_key,
                        "title": title,
                        "message": message,
                        "url": "sigmaris://chat",
                        "url_title": "シグマリスを開く",
                    },
                )
            if response.is_error:
                logger.error("Pushover error %s: %s", response.status_code, response.text[:200])
                return False
            return True
        except Exception:
            logger.exception("Pushover send failed")
            return False


class LogNotifier(BaseNotifier):
    async def send(self, title: str, message: str) -> bool:
        logger.info("[LogNotifier] %s — %s", title, message)
        return True


def get_notifier() -> BaseNotifier:
    if settings.pushover_app_token and settings.pushover_user_key:
        return PushoverNotifier(
            app_token=settings.pushover_app_token,
            user_key=settings.pushover_user_key,
        )
    logger.warning("Pushover not configured; using LogNotifier fallback")
    return LogNotifier()
