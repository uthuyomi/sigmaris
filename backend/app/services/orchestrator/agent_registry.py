from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    base_url: str
    chat_endpoint: str
    capabilities: tuple[str, ...]
    description: str = ""


class AgentRegistry:
    """Runtime registry of agent definitions.

    Agents are registered at startup from two sources (in order):
    1. Legacy env vars (SCHEDULE_AGENT_BASE_URL) — always registered for backward compat.
    2. AGENT_REGISTRY_JSON — JSON array of additional agent entries.

    Once registered an agent definition is immutable for the lifetime of the process.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}

    def register(
        self,
        agent_id: str,
        base_url: str,
        *,
        chat_endpoint: str = "/api/agent/chat/complete",
        capabilities: tuple[str, ...] = (),
        description: str = "",
    ) -> AgentDefinition:
        defn = AgentDefinition(
            agent_id=agent_id,
            base_url=base_url.rstrip("/"),
            chat_endpoint=chat_endpoint,
            capabilities=capabilities,
            description=description,
        )
        self._agents[agent_id] = defn
        logger.debug("AgentRegistry: registered '%s' at %s", agent_id, base_url)
        return defn

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise KeyError(f"Agent '{agent_id}' is not registered. Available: {list(self._agents)}")

    def list(self) -> list[AgentDefinition]:
        return list(self._agents.values())


# ─── Module-level singleton ───────────────────────────────────────────────────

_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def _build_registry() -> AgentRegistry:
    r = AgentRegistry()

    # 1. Legacy env vars — always register schedule-agent for backward compat.
    r.register(
        agent_id="schedule-agent",
        base_url=settings.schedule_agent_base_url,
        chat_endpoint="/api/agent/chat/complete",
        capabilities=("schedule", "calendar", "travel", "google-sheets"),
        description="スケジュール管理エージェント",
    )

    # 2. AGENT_REGISTRY_JSON — additional agents declared at deployment time.
    #    Format: [{"id":"x","base_url":"http://...","description":"...","capabilities":[],"chat_endpoint":"..."}]
    if settings.agent_registry_json:
        try:
            entries = json.loads(settings.agent_registry_json)
            if not isinstance(entries, list):
                logger.error("AgentRegistry: AGENT_REGISTRY_JSON must be a JSON array")
            else:
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    agent_id = str(entry.get("id", "")).strip()
                    base_url = str(entry.get("base_url", "")).strip()
                    if not agent_id or not base_url:
                        logger.warning("AgentRegistry: skipping invalid entry (missing id/base_url): %s", entry)
                        continue
                    r.register(
                        agent_id=agent_id,
                        base_url=base_url,
                        chat_endpoint=str(entry.get("chat_endpoint", "/api/agent/chat/complete")),
                        capabilities=tuple(entry.get("capabilities") or []),
                        description=str(entry.get("description", "")),
                    )
        except json.JSONDecodeError:
            logger.error("AgentRegistry: AGENT_REGISTRY_JSON is not valid JSON — skipping extra agents")

    logger.info("AgentRegistry: %d agent(s) registered: %s", len(r.list()), [a.agent_id for a in r.list()])
    return r


# ─── Backward-compatible alias ────────────────────────────────────────────────

def get_schedule_agent() -> AgentDefinition:
    """Return the schedule-agent definition (backward-compatible alias)."""
    return get_registry().get("schedule-agent")
