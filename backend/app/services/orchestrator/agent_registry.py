from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    base_url: str
    chat_endpoint: str
    capabilities: tuple[str, ...]


def get_schedule_agent() -> AgentDefinition:
    return AgentDefinition(
        agent_id="schedule-agent",
        base_url=settings.schedule_agent_base_url.rstrip("/"),
        chat_endpoint="/api/agent/chat/complete",
        capabilities=("schedule", "calendar", "travel", "google-sheets"),
    )
