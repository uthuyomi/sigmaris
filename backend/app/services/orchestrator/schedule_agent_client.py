from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.services.orchestrator.agent_registry import AgentDefinition


_BASE_SYSTEM_OVERRIDE = (
    "Return the schedule analysis and execution result accurately and plainly. "
    "Do not role-play Sigmaris and do not add a separate personality layer. "
    "Preserve dates, times, counts, URLs, named entities, warnings, and success "
    "or failure states explicitly so another service can render the final tone."
)


def _build_system_override(user_profile_context: str | None) -> str:
    if user_profile_context:
        return f"{user_profile_context}\n\n{_BASE_SYSTEM_OVERRIDE}"
    return _BASE_SYSTEM_OVERRIDE


@dataclass(frozen=True)
class ScheduleAgentResult:
    text: str
    thread_id: str
    message_id: str | None


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
) -> ScheduleAgentResult:
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

    payload: dict[str, Any] = {
        "thread_id": thread_id,
        "messages": [
            {
                "role": message["role"],
                "parts": [{"type": "text", "text": message["content"]}],
            }
            for message in messages
        ],
        "persist_thread": False,
        "system_override": _build_system_override(user_profile_context),
        "context": {
            "reason": reason,
            "invocationId": invocation_id,
            "callerAgentId": settings.schedule_agent_id,
        },
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
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
