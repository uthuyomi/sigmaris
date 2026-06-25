from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import urllib.parse
import uuid
from abc import ABC, abstractmethod
from typing import Literal

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PostType = Literal["daily_log", "milestone", "observation", "self_reflection"]

_TWITTER_API_V2_TWEET = "https://api.twitter.com/2/tweets"


# ─── OAuth 1.0a helper ───────────────────────────────────────────────────────


def _percent_encode(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def _build_oauth_header(
    method: str,
    url: str,
    body_params: dict[str, str],
    *,
    api_key: str,
    api_secret: str,
    access_token: str,
    access_token_secret: str,
) -> str:
    oauth_params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    all_params = {**body_params, **oauth_params}
    sorted_params = sorted(
        (_percent_encode(k), _percent_encode(v)) for k, v in all_params.items()
    )
    param_string = "&".join(f"{k}={v}" for k, v in sorted_params)

    base_string = "&".join([
        _percent_encode(method.upper()),
        _percent_encode(url),
        _percent_encode(param_string),
    ])

    signing_key = f"{_percent_encode(api_secret)}&{_percent_encode(access_token_secret)}"
    signature = hmac.new(
        signing_key.encode(),
        base_string.encode(),
        hashlib.sha1,
    ).digest()

    import base64
    oauth_params["oauth_signature"] = base64.b64encode(signature).decode()

    header_parts = ", ".join(
        f'{_percent_encode(k)}="{_percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"


# ─── Publisher base / implementations ────────────────────────────────────────


class BasePublisher(ABC):
    @abstractmethod
    async def post_tweet(self, text: str) -> bool: ...


class XPublisher(BasePublisher):
    """Posts to X (Twitter) via API v2 with OAuth 1.0a user-context auth."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_token_secret: str,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token
        self._access_token_secret = access_token_secret

    async def post_tweet(self, text: str) -> bool:
        auth_header = _build_oauth_header(
            "POST",
            _TWITTER_API_V2_TWEET,
            {},
            api_key=self._api_key,
            api_secret=self._api_secret,
            access_token=self._access_token,
            access_token_secret=self._access_token_secret,
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                r = await client.post(
                    _TWITTER_API_V2_TWEET,
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/json",
                    },
                    json={"text": text},
                )
                if r.is_error:
                    logger.error("X post failed HTTP %s: %s", r.status_code, r.text[:200])
                    return False
                data = r.json()
                tweet_id = data.get("data", {}).get("id")
                logger.info("X posted tweet_id=%s", tweet_id)
                return True
        except Exception:
            logger.exception("X post raised an exception")
            return False


class LogPublisher(BasePublisher):
    """Fallback publisher that logs instead of posting."""

    async def post_tweet(self, text: str) -> bool:
        logger.info("[X fallback] would post: %s", text)
        return True


# ─── Format helper ───────────────────────────────────────────────────────────


def _days_since_launch() -> int | None:
    raw = settings.sigmaris_launch_date
    if not raw:
        return None
    try:
        from datetime import date
        launch = date.fromisoformat(raw)
        return (date.today() - launch).days + 1
    except ValueError:
        return None


def format_sigmaris_post(content: str, post_type: PostType) -> str:
    if post_type == "daily_log":
        n = _days_since_launch()
        day_str = f"起動{n}日目。" if n is not None else ""
        return f"{day_str}{content} #Sigmaris #家庭支援AI"

    if post_type == "milestone":
        return f"{content} #Sigmaris"

    if post_type == "observation":
        return f"[観察] {content} #Sigmaris"

    if post_type == "self_reflection":
        return f"[自己反省] {content} #Sigmaris"

    return content


# ─── Factory ─────────────────────────────────────────────────────────────────


def get_publisher() -> BasePublisher:
    if not settings.x_enabled:
        return LogPublisher()

    if not all([
        settings.x_api_key,
        settings.x_api_secret,
        settings.x_access_token,
        settings.x_access_token_secret,
    ]):
        logger.warning("X_ENABLED=true but credentials are incomplete — using LogPublisher")
        return LogPublisher()

    return XPublisher(
        api_key=settings.x_api_key,  # type: ignore[arg-type]
        api_secret=settings.x_api_secret,  # type: ignore[arg-type]
        access_token=settings.x_access_token,  # type: ignore[arg-type]
        access_token_secret=settings.x_access_token_secret,  # type: ignore[arg-type]
    )
