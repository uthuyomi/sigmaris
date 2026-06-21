from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class OrchestratorMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class OrchestratorChatRequest(BaseModel):
    messages: list[OrchestratorMessage] = Field(min_length=1, max_length=50)
    thread_id: str | None = Field(default=None, max_length=80)
    context: dict[str, Any] | None = None


class OrchestratorChatResponse(BaseModel):
    ok: bool = True
    text: str
    thread_id: str
    invocation_id: str
    agent_id: str
    used_fallback: bool = False
