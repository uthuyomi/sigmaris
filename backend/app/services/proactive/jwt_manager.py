from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_REFRESH_MARGIN = 300  # refresh 5 minutes before expiry

# Supabase refresh tokens are single-use (rotation): every successful
# refresh invalidates the token that was just used and issues a new one.
# That new token used to live only in the in-memory _state below — so the
# process could rotate correctly for as long as it stayed alive, but a
# restart had nothing but the original (by-then long since consumed) value
# in backend/.env to bootstrap from, and would immediately hit
# "refresh_token_already_used". _STATE_FILE persists the latest rotation to
# disk specifically so a restart can pick up where the process left off.
# .env's SIGMARIS_USER_JWT/SIGMARIS_REFRESH_TOKEN remain the fallback for
# the very first run, before this file exists.
_STATE_FILE = Path(__file__).resolve().parents[3] / ".state" / "sigmaris_jwt_session.json"


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


def _load_persisted_state() -> _TokenState | None:
    """Read the last successfully-rotated token pair from disk. Returns None
    on any problem (missing file, corrupt JSON, wrong shape) — callers treat
    that exactly like "nothing persisted yet" and fall back to env vars."""
    try:
        if not _STATE_FILE.exists():
            return None
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_at = data.get("expires_at")
        if not isinstance(access_token, str) or not access_token:
            return None
        if not isinstance(refresh_token, str) or not refresh_token:
            return None
        if not isinstance(expires_at, (int, float)):
            return None
        return _TokenState(
            access_token=access_token, refresh_token=refresh_token, expires_at=float(expires_at)
        )
    except Exception:
        logger.exception("jwt_manager: failed to read persisted state file (falling back to env bootstrap)")
        return None


def _persist_state(state: _TokenState) -> None:
    """Best-effort write-through to disk after a successful rotation.

    This is a safety net, not a dependency: any failure here (disk full,
    permissions, read-only filesystem) is logged and swallowed so the
    in-memory auto-refresh chain — which is what actually keeps the process
    serving requests — is never affected. Never logs token values, only
    success/failure.
    """
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": state.access_token,
            "refresh_token": state.refresh_token,
            "expires_at": state.expires_at,
            "persisted_at": datetime.now(UTC).isoformat(),
        }
        tmp_path = _STATE_FILE.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            tmp_path.chmod(0o600)
        except Exception:
            pass  # best-effort; e.g. no-op on Windows dev machines
        tmp_path.replace(_STATE_FILE)  # atomic rename, avoids partial-write corruption
        logger.info("jwt_manager: persisted refreshed token state to disk (ok)")
    except Exception:
        logger.exception("jwt_manager: failed to persist refreshed token state (in-memory state unaffected)")


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
    """Return a valid access token, refreshing automatically when near expiry.

    Bootstrap priority: persisted state file (the latest known-good rotation,
    written by a prior successful refresh — possibly from an earlier process
    lifetime) takes priority over SIGMARIS_USER_JWT/SIGMARIS_REFRESH_TOKEN in
    .env, which are only the fallback for the very first run before any
    state has been persisted yet.
    """
    global _state

    refresh_token_env = settings.sigmaris_refresh_token

    if not refresh_token_env and _load_persisted_state() is None:
        # No refresh capability at all (never configured, nothing persisted
        # yet) — use static JWT as-is, exactly as before persistence existed.
        static = settings.sigmaris_user_jwt
        if not static:
            raise RuntimeError(
                "Neither SIGMARIS_REFRESH_TOKEN nor SIGMARIS_USER_JWT is configured, "
                "and no persisted JWT state exists."
            )
        logger.warning(
            "SIGMARIS_REFRESH_TOKEN not set and no persisted state found; "
            "using static JWT (will not auto-refresh)"
        )
        return static

    async with _get_lock():
        if _state is None:
            persisted = _load_persisted_state()
            if persisted is not None:
                _state = persisted
                logger.info(
                    "Sigmaris JWT bootstrapped from persisted state file (expires_at=%.0f)",
                    _state.expires_at,
                )
            elif settings.sigmaris_user_jwt:
                # No persisted state (e.g. very first run) — fall back to the
                # env bootstrap exactly as before this feature existed.
                candidate = _bootstrap(settings.sigmaris_user_jwt, refresh_token_env)
                if candidate and _is_fresh(candidate):
                    _state = candidate
                    logger.info(
                        "Sigmaris JWT bootstrapped from SIGMARIS_USER_JWT env var "
                        "(expires_at=%.0f, no persisted state found)",
                        _state.expires_at,
                    )

        if _state is not None and _is_fresh(_state):
            return _state.access_token

        # Need to refresh — use the most recent refresh token we have
        # (persisted/in-memory takes priority over the .env fallback).
        current_refresh = _state.refresh_token if _state is not None else refresh_token_env
        if not current_refresh:
            raise RuntimeError(
                "No refresh token available (persisted state had none, "
                "and SIGMARIS_REFRESH_TOKEN is not set)."
            )

        logger.info("Refreshing Sigmaris JWT (current_refresh=…%s)", current_refresh[-6:])
        try:
            new_state = await _do_refresh(current_refresh)
        except Exception as exc:
            # If the rotated/persisted token failed, fall back to the env token once.
            if _state is not None and refresh_token_env and current_refresh != refresh_token_env:
                logger.warning(
                    "Rotated refresh token failed (%s); retrying with env token", exc
                )
                new_state = await _do_refresh(refresh_token_env)
            else:
                raise

        _state = new_state
        _persist_state(new_state)
        logger.info("Sigmaris JWT refreshed (expires_at=%.0f)", _state.expires_at)
        return _state.access_token
