from __future__ import annotations

import enum
import logging
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class TaskType(str, enum.Enum):
    ROUTING = "routing"
    MEMORY_EXTRACTION = "memory_extraction"
    SELF_REFLECT = "self_reflect"
    SUMMARIZE = "summarize"
    COMPLEX_REASONING = "complex_reasoning"


_LOCAL_TASK_TYPES = {
    TaskType.ROUTING,
    TaskType.MEMORY_EXTRACTION,
    TaskType.SELF_REFLECT,
    TaskType.SUMMARIZE,
}


class LocalLLMClient:
    """Thin async client for Ollama /api/chat."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.post(f"{self._base_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
            return data["message"]["content"]

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                r = await client.get(f"{self._base_url}/api/tags")
                return r.is_success
        except Exception:
            return False


class _OpenAIAdapter:
    """Wraps AsyncOpenAI to expose the same chat() interface as LocalLLMClient."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": settings.sigmaris_reflect_model or settings.openai_model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""


class LLMRouter:
    """
    Routes task types to LocalLLMClient or OpenAI.

    Uses local LLM when LOCAL_LLM_ENABLED=true AND Ollama is reachable
    AND the task type is in the local-eligible set. Falls back to OpenAI
    automatically if Ollama is unavailable.
    """

    def __init__(self) -> None:
        self._local: LocalLLMClient | None = None
        self._openai = _OpenAIAdapter()
        self._local_available: bool | None = None  # None = not yet probed

        if settings.local_llm_enabled:
            self._local = LocalLLMClient(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
            )

    async def _get_backend(self, task: TaskType) -> LocalLLMClient | _OpenAIAdapter:
        if not settings.local_llm_enabled or self._local is None:
            return self._openai

        if task not in _LOCAL_TASK_TYPES:
            return self._openai

        # Probe availability once per router lifetime (lazy).
        if self._local_available is None:
            self._local_available = await self._local.is_available()
            if not self._local_available:
                logger.warning(
                    "Ollama not reachable at %s — falling back to OpenAI for all local tasks.",
                    settings.ollama_base_url,
                )

        return self._local if self._local_available else self._openai

    async def chat(
        self,
        task: TaskType,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        backend = await self._get_backend(task)
        backend_name = "local" if isinstance(backend, LocalLLMClient) else "openai"
        logger.debug("LLMRouter task=%s backend=%s", task.value, backend_name)
        return await backend.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )


# Module-level singleton — created lazily to avoid import-time side effects.
_router: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
