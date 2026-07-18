from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import urllib.parse
import uuid
from abc import ABC, abstractmethod
from typing import Any, Literal

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PostType = Literal["daily_log", "milestone", "observation", "self_reflection"]

_TWITTER_API_V2_TWEET = "https://api.twitter.com/2/tweets"
_TWITTER_API_V2_USERS_ME = "https://api.twitter.com/2/users/me"
_TWITTER_API_V2_MENTIONS_TEMPLATE = "https://api.twitter.com/2/users/{user_id}/mentions"


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
    async def post_tweet(self, text: str, *, in_reply_to_tweet_id: str | None = None) -> str | None:
        """成功時は投稿のtweet_id、失敗時はNoneを返す。

        【Phase H-2追記(docs/sigmaris/phase_h_report.md)】返信検知には、
        「どの投稿への返信か」を突き合わせるためのtweet_idが必須のため、
        戻り値をbool(投稿できたか否か)からstr | None(実際のtweet_id、
        またはNone)へ変更した。既存の呼び出し元(`if posted:`という
        真偽値チェック)は、非空文字列=truthy・None=falsyという性質上、
        コードの変更なしに引き続き正しく動作する(判断根拠、レポート
        参照)。

        【Phase H-3追記】in_reply_to_tweet_id(既定None)を追加した。
        依頼書は「既存のpost_tweet()を使うこと」としていたが、Noneの
        ままでは、投稿がXの返信スレッドとして相手の投稿に繋がらず、
        無関係な独立ツイートになってしまう(=「返信」という機能が
        実質的に成立しない)。既存の全呼び出し元(_categorized_x_post_
        check()等、H-1由来の独り言投稿)はin_reply_to_tweet_idを渡さない
        ため、既定値Noneにより、それらの挙動は一切変わらない——後方
        互換な、追加のキーワード専用引数として拡張した(判断根拠、
        レポート参照)。"""
        ...

    @abstractmethod
    async def get_own_user_id(self) -> str | None:
        """自分自身(投稿元)のXユーザーIDを返す。取得できない場合はNone。
        Phase H-2: 返信検知(mentions APIの呼び出し)に必要。"""
        ...

    @abstractmethod
    async def fetch_mentions(self, *, max_results: int = 50) -> list[dict[str, Any]]:
        """自分宛のメンション(返信を含む)を、新しい順に返す。各要素は
        少なくとも `id`・`text`・`author_id`・`referenced_tweets`
        (type="replied_to"の要素を含みうる)を持つ。取得できない場合は
        空リスト。Phase H-2: 返信検知に使う、唯一のX API読み取り経路。"""
        ...


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

    async def post_tweet(self, text: str, *, in_reply_to_tweet_id: str | None = None) -> str | None:
        auth_header = _build_oauth_header(
            "POST",
            _TWITTER_API_V2_TWEET,
            {},
            api_key=self._api_key,
            api_secret=self._api_secret,
            access_token=self._access_token,
            access_token_secret=self._access_token_secret,
        )
        body: dict[str, Any] = {"text": text}
        if in_reply_to_tweet_id:
            body["reply"] = {"in_reply_to_tweet_id": in_reply_to_tweet_id}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                r = await client.post(
                    _TWITTER_API_V2_TWEET,
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                if r.is_error:
                    logger.error("X post failed HTTP %s: %s", r.status_code, r.text[:200])
                    return None
                data = r.json()
                tweet_id = data.get("data", {}).get("id")
                logger.info("X posted tweet_id=%s", tweet_id)
                return tweet_id if isinstance(tweet_id, str) else None
        except Exception:
            logger.exception("X post raised an exception")
            return None

    async def get_own_user_id(self) -> str | None:
        auth_header = _build_oauth_header(
            "GET",
            _TWITTER_API_V2_USERS_ME,
            {},
            api_key=self._api_key,
            api_secret=self._api_secret,
            access_token=self._access_token,
            access_token_secret=self._access_token_secret,
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                r = await client.get(
                    _TWITTER_API_V2_USERS_ME,
                    headers={"Authorization": auth_header},
                )
                if r.is_error:
                    logger.error("X get_own_user_id failed HTTP %s: %s", r.status_code, r.text[:200])
                    return None
                user_id = r.json().get("data", {}).get("id")
                return user_id if isinstance(user_id, str) else None
        except Exception:
            logger.exception("X get_own_user_id raised an exception")
            return None

    async def fetch_mentions(self, *, max_results: int = 50) -> list[dict[str, Any]]:
        user_id = await self.get_own_user_id()
        if not user_id:
            logger.warning("X fetch_mentions: could not resolve own user_id, skipping")
            return []

        url = _TWITTER_API_V2_MENTIONS_TEMPLATE.format(user_id=user_id)
        params = {
            "max_results": str(max(5, min(max_results, 100))),
            "tweet.fields": "author_id,created_at,in_reply_to_user_id,referenced_tweets,conversation_id",
            "expansions": "author_id",
            "user.fields": "username",
        }
        auth_header = _build_oauth_header(
            "GET", url, {}, api_key=self._api_key, api_secret=self._api_secret,
            access_token=self._access_token, access_token_secret=self._access_token_secret,
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                r = await client.get(url, headers={"Authorization": auth_header}, params=params)
                if r.is_error:
                    logger.error("X fetch_mentions failed HTTP %s: %s", r.status_code, r.text[:200])
                    return []
                payload = r.json()
                tweets = payload.get("data", [])
                users_by_id = {
                    u["id"]: u for u in payload.get("includes", {}).get("users", []) if isinstance(u, dict) and u.get("id")
                }
                for tweet in tweets:
                    author = users_by_id.get(tweet.get("author_id"))
                    if author:
                        tweet["author_username"] = author.get("username")
                return tweets if isinstance(tweets, list) else []
        except Exception:
            logger.exception("X fetch_mentions raised an exception")
            return []


class LogPublisher(BasePublisher):
    """Fallback publisher that logs instead of posting."""

    async def post_tweet(self, text: str, *, in_reply_to_tweet_id: str | None = None) -> str | None:
        if in_reply_to_tweet_id:
            logger.info("[X fallback] would post as reply to %s: %s", in_reply_to_tweet_id, text)
        else:
            logger.info("[X fallback] would post: %s", text)
        return f"log-{uuid.uuid4().hex[:12]}"

    async def get_own_user_id(self) -> str | None:
        return None

    async def fetch_mentions(self, *, max_results: int = 50) -> list[dict[str, Any]]:
        logger.info("[X fallback] fetch_mentions: X未接続のため0件を返す")
        return []


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
