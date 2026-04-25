from __future__ import annotations

# 役割: Supabase REST API への共通アクセス処理を提供する。

from typing import Any

import httpx

from app.config import settings


def _require_supabase_config() -> tuple[str, str]:
    if not settings.next_public_supabase_url or not settings.next_public_supabase_publishable_key:
        raise RuntimeError("Supabase environment variables are not fully configured for backend.")
    return settings.next_public_supabase_url, settings.next_public_supabase_publishable_key


def _headers(jwt: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    _, apikey = _require_supabase_config()
    base = {
        "apikey": apikey,
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
    }
    if extra:
        base.update(extra)
    return base


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        detail = response.text.strip()
        message = (
            f"Supabase REST {response.status_code} {response.reason_phrase}"
            f" for {response.request.method} {response.request.url}"
        )
        if detail:
            message = f"{message}: {detail}"
        raise RuntimeError(message) from error


async def get_current_user(jwt: str) -> dict[str, Any]:
    base_url, _ = _require_supabase_config()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{base_url}/auth/v1/user",
            headers=_headers(jwt),
        )
        _raise_for_status(response)
        return response.json()


async def rest_select(
    jwt: str,
    table: str,
    params: dict[str, str],
    *,
    single: bool = False,
) -> Any:
    base_url, _ = _require_supabase_config()
    headers = _headers(jwt, {"Accept": "application/vnd.pgrst.object+json"} if single else None)
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{base_url}/rest/v1/{table}",
            headers=headers,
            params=params,
        )
        if response.status_code == 406 and single:
            return None
        _raise_for_status(response)
        return response.json()


async def rest_insert(jwt: str, table: str, payload: Any, *, single: bool = False) -> Any:
    base_url, _ = _require_supabase_config()
    headers = _headers(jwt, {"Prefer": "return=representation"})
    if single:
        headers["Accept"] = "application/vnd.pgrst.object+json"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{base_url}/rest/v1/{table}",
            headers=headers,
            json=payload,
        )
        _raise_for_status(response)
        return response.json()


async def rest_update(
    jwt: str,
    table: str,
    payload: Any,
    params: dict[str, str],
) -> Any:
    base_url, _ = _require_supabase_config()
    headers = _headers(jwt, {"Prefer": "return=representation"})
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.patch(
            f"{base_url}/rest/v1/{table}",
            headers=headers,
            params=params,
            json=payload,
        )
        _raise_for_status(response)
        return response.json()


async def rest_delete(jwt: str, table: str, params: dict[str, str]) -> None:
    base_url, _ = _require_supabase_config()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.delete(
            f"{base_url}/rest/v1/{table}",
            headers=_headers(jwt),
            params=params,
        )
        _raise_for_status(response)
