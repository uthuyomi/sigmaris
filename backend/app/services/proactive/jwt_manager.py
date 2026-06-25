from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import NamedTuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_REFRESH_MARGIN = 300  # refresh 5 minutes before expiry


class _TokenState(NamedTuple):
    access_token: str
    refresh_token: str
    expires_at: float  # unix timestamp


_state: _TokenState | None = None
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _decode_exp(jwt: str) -> float | None:
    try:
        parts = jwt.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        rem = len(payload) % 4
        if rem:
            payload += "=" * (4 - rem)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


def _is_fresh(state: _TokenState) -> bool:
    return time.time() < state.expires_at - _REFRESH_MARGIN


def _bootstrap(access_token: str, refresh_token: str) -> _TokenState | None:
    """Build initial state from a static JWT + env refresh token (no network)."""
    exp = _decode_exp(access_token)
    if exp is None:
        return None
    return _TokenState(access_token=access_token, refresh_token=refresh_token, expires_at=exp)


async def _do_refresh(refresh_token: str) -> _TokenState:
    supabase_url = settings.next_public_supabase_url
    anon_key = settings.next_public_supabase_publishable_key
    if not supabase_url or not anon_key:
        raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL or publishable key not configured.")

    url = f"{supabase_url.rstrip('/')}/auth/v1/token?grant_type=refresh_token"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            url,
            headers={"apikey": anon_key, "Content-Type": "application/json"},
            json={"refresh_token": refresh_token},
        )

    if response.is_error:
        raise RuntimeError(
            f"Supabase token refresh failed {response.status_code}: {response.text[:200]}"
        )

    data = response.json()
    new_access = data.get("access_token")
    new_refresh = data.get("refresh_token") or refresh_token  # Supabase rotates the token
    expires_in = data.get("expires_in", 3600)

    if not isinstance(new_access, str) or not new_access:
        raise RuntimeError("Supabase token refresh response missing access_token.")

    exp = _decode_exp(new_access)
    expires_at = exp if exp is not None else time.time() + float(expires_in)

    return _TokenState(access_token=new_access, refresh_token=new_refresh, expires_at=expires_at)


async def get_sigmaris_jwt() -> str:
    """Return a valid access token, refreshing automatically when near expiry."""
    global _state

    refresh_token_env = settings.sigmaris_refresh_token

    if not refresh_token_env:
        # No refresh token configured — use static JWT as-is.
        static = settings.sigmaris_user_jwt
        if not static:
            raise RuntimeError(
                "Neither SIGMARIS_REFRESH_TOKEN nor SIGMARIS_USER_JWT is configured."
            )
        logger.warning(
            "SIGMARIS_REFRESH_TOKEN not set; using static JWT (will not auto-refresh)"
        )
        return static

    async with _get_lock():
        # First call: try to bootstrap from static JWT to avoid an immediate network hit.
        if _state is None and settings.sigmaris_user_jwt:
            candidate = _bootstrap(settings.sigmaris_user_jwt, refresh_token_env)
            if candidate and _is_fresh(candidate):
                _state = candidate
                logger.info(
                    "Sigmaris JWT bootstrapped from SIGMARIS_USER_JWT (expires_at=%.0f)",
                    _state.expires_at,
                )

        if _state is not None and _is_fresh(_state):
            return _state.access_token

        # Need to refresh — use the most recent refresh token we have.
        current_refresh = _state.refresh_token if _state is not None else refresh_token_env
        logger.info("Refreshing Sigmaris JWT (current_refresh=…%s)", current_refresh[-6:])
        try:
            new_state = await _do_refresh(current_refresh)
        except Exception as exc:
            # If the rotated token failed, fall back to the env token once.
            if _state is not None and current_refresh != refresh_token_env:
                logger.warning(
                    "Rotated refresh token failed (%s); retrying with env token", exc
                )
                new_state = await _do_refresh(refresh_token_env)
            else:
                raise

        _state = new_state
        logger.info("Sigmaris JWT refreshed (expires_at=%.0f)", _state.expires_at)
        return _state.access_token
