from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.config import settings
from app.services.orchestrator.agent_registry import AgentDefinition

# Persistent connection pool — created on first call, closed on app shutdown.
_http_client: httpx.AsyncClient | None = None


async def startup_schedule_agent_http_client() -> None:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )


async def shutdown_schedule_agent_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


async def _get_http_client() -> httpx.AsyncClient:
    if _http_client is None:
        await startup_schedule_agent_http_client()
    if _http_client is None:
        raise RuntimeError("Schedule agent HTTP client is not available.")
    return _http_client


_BASE_SYSTEM_OVERRIDE = (
    "Return the schedule analysis and execution result accurately and plainly. "
    "Do not role-play Sigmaris and do not add a separate personality layer. "
    "Preserve dates, times, counts, URLs, named entities, warnings, and success "
    "or failure states explicitly so another service can render the final tone."
)


def _build_system_override(
    user_profile_context: str | None,
    self_model_context: str | None = None,
) -> str:
    parts = []
    if user_profile_context:
        parts.append(user_profile_context)
    if self_model_context:
        parts.append(self_model_context)
    parts.append(_BASE_SYSTEM_OVERRIDE)
    return "\n\n".join(parts)


@dataclass(frozen=True)
class ScheduleAgentResult:
    text: str
    thread_id: str
    message_id: str | None


@dataclass(frozen=True)
class ScheduleAgentStreamEvent:
    delta: str = ""
    thread_id: str | None = None
    message_id: str | None = None
    done: bool = False
    tool_event: dict[str, Any] | None = None


def _build_headers(
    *,
    jwt: str,
    google_access_token: str | None,
    google_refresh_token: str | None,
    invocation_id: str,
) -> dict[str, str]:
    if not settings.schedule_agent_secret:
        raise RuntimeError("SCHEDULE_AGENT_SECRET is not configured.")

    headers = {
        "Authorization": f"Bearer {jwt}",
        "X-Agent-ID": settings.schedule_agent_id,
        "X-Agent-Secret": settings.schedule_agent_secret,
        "X-Correlation-ID": invocation_id,
        "Content-Type": "application/json",
    }
    if google_access_token:
        headers["X-Google-Access-Token"] = google_access_token
    if google_refresh_token:
        headers["X-Google-Refresh-Token"] = google_refresh_token
    return headers


def _build_payload(
    *,
    messages: list[dict[str, str]],
    thread_id: str | None,
    invocation_id: str,
    reason: str,
    user_profile_context: str | None = None,
    self_model_context: str | None = None,
    persist_thread: bool = False,
) -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "messages": [
            {
                "role": message["role"],
                "parts": [{"type": "text", "text": message["content"]}],
            }
            for message in messages
        ],
        "persist_thread": persist_thread,
        "system_override": _build_system_override(user_profile_context, self_model_context),
        "context": {
            "reason": reason,
            "invocationId": invocation_id,
            "callerAgentId": settings.schedule_agent_id,
        },
    }


async def call_schedule_agent(
    *,
    agent: AgentDefinition,
    jwt: str,
    google_access_token: str | None,
    google_refresh_token: str | None,
    messages: list[dict[str, str]],
    thread_id: str | None,
    invocation_id: str,
    reason: str,
    user_profile_context: str | None = None,
    self_model_context: str | None = None,
    persist_thread: bool = False,
) -> ScheduleAgentResult:
    headers = _build_headers(
        jwt=jwt,
        google_access_token=google_access_token,
        google_refresh_token=google_refresh_token,
        invocation_id=invocation_id,
    )
    payload = _build_payload(
        messages=messages,
        thread_id=thread_id,
        invocation_id=invocation_id,
        reason=reason,
        user_profile_context=user_profile_context,
        self_model_context=self_model_context,
        persist_thread=persist_thread,
    )

    client = await _get_http_client()
    response = await client.post(
        f"{agent.base_url}{agent.chat_endpoint}",
        headers=headers,
        json=payload,
    )

    if response.is_error:
        detail = response.text.strip()
        raise RuntimeError(
            f"Schedule agent returned HTTP {response.status_code}"
            + (f": {detail}" if detail else "")
        )

    data = response.json()
    text = data.get("text")
    returned_thread_id = data.get("thread_id")
    if not isinstance(text, str) or not text.strip() or not isinstance(returned_thread_id, str):
        raise RuntimeError("Schedule agent returned an invalid response.")

    return ScheduleAgentResult(
        text=text,
        thread_id=returned_thread_id,
        message_id=data.get("message_id") if isinstance(data.get("message_id"), str) else None,
    )


async def call_schedule_agent_stream(
    *,
    agent: AgentDefinition,
    jwt: str,
    google_access_token: str | None,
    google_refresh_token: str | None,
    messages: list[dict[str, str]],
    thread_id: str | None,
    invocation_id: str,
    reason: str,
    user_profile_context: str | None = None,
    self_model_context: str | None = None,
    persist_thread: bool = False,
) -> AsyncGenerator[ScheduleAgentStreamEvent, None]:
    headers = _build_headers(
        jwt=jwt,
        google_access_token=google_access_token,
        google_refresh_token=google_refresh_token,
        invocation_id=invocation_id,
    )
    headers["Accept"] = "text/event-stream"
    payload = _build_payload(
        messages=messages,
        thread_id=thread_id,
        invocation_id=invocation_id,
        reason=reason,
        user_profile_context=user_profile_context,
        self_model_context=self_model_context,
        persist_thread=persist_thread,
    )
    stream_endpoint = agent.chat_endpoint.replace("/complete", "/stream")

    client = await _get_http_client()
    async with client.stream(
        "POST",
        f"{agent.base_url}{stream_endpoint}",
        headers=headers,
        json=payload,
    ) as response:
            if response.is_error:
                detail = (await response.aread()).decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    f"Schedule agent stream returned HTTP {response.status_code}"
                    + (f": {detail}" if detail else "")
                )

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(event.get("error"), str):
                    raise RuntimeError(event["error"])
                if isinstance(event.get("tool_event"), dict):
                    yield ScheduleAgentStreamEvent(tool_event=event["tool_event"])
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    yield ScheduleAgentStreamEvent(delta=delta)
                if event.get("done"):
                    yield ScheduleAgentStreamEvent(
                        done=True,
                        thread_id=event.get("thread_id") if isinstance(event.get("thread_id"), str) else None,
                        message_id=event.get("message_id") if isinstance(event.get("message_id"), str) else None,
                    )
                    return
