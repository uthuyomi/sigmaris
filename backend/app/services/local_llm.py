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
    DECISION_DETECTION = "decision_detection"
    EPISODE_DETECTION = "episode_detection"
    TOPIC_DETECTION = "topic_detection"
    QUERY_DECOMPOSITION = "query_decomposition"
    MEMORY_RERANK = "memory_rerank"
    ABSTENTION_REACTION_DETECTION = "abstention_reaction_detection"
    EVAL_GENERATION = "eval_generation"


_LOCAL_TASK_TYPES = {
    TaskType.ROUTING,
    TaskType.MEMORY_EXTRACTION,
    TaskType.SELF_REFLECT,
    TaskType.SUMMARIZE,
    TaskType.DECISION_DETECTION,
    TaskType.EPISODE_DETECTION,
    TaskType.TOPIC_DETECTION,
    TaskType.QUERY_DECOMPOSITION,
    TaskType.MEMORY_RERANK,
    TaskType.ABSTENTION_REACTION_DETECTION,
    TaskType.EVAL_GENERATION,
}


class LocalLLMClient:
    """Thin async client for Ollama /api/chat with persistent connection pool."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

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

        r = await self._client.post(f"{self._base_url}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
        return data["message"]["content"]

    async def is_available(self) -> bool:
        """Whether Ollama is not just reachable, but actually has the
        configured chat model (self._model) installed.

        A bare "does /api/tags respond" check used to be enough to mark
        Ollama "available" and route chat-eligible tasks to it — but a
        server can have Ollama running with only an embedding model
        installed (e.g. nomic-embed-text) and no chat model at all. That
        looked "available" here, so every local-eligible TaskType got
        routed to Ollama and then hit a 404 on POST /api/chat, with no
        fallback (LLMRouter.chat() picks a backend once via this check and
        does not retry on failure). Checking the model list directly here
        means the OpenAI fallback triggers up front instead.
        """
        try:
            r = await self._client.get(f"{self._base_url}/api/tags")
            if not r.is_success:
                return False
            data = r.json()
            models = data.get("models", [])
            installed = {
                str(entry.get(field))
                for entry in models
                if isinstance(entry, dict)
                for field in ("name", "model")
                if entry.get(field)
            }
            if self._model in installed:
                return True
            # Fall back to a base-name match (ignoring the ":tag" suffix) in
            # case the configured model omits a tag that Ollama fills in
            # (e.g. ":latest") or vice versa.
            base_name = self._model.split(":", 1)[0]
            return any(name.split(":", 1)[0] == base_name for name in installed)
        except Exception:
            return False


def _openai_model_for_task(task: TaskType) -> str:
    """Map TaskType to the appropriate OpenAI model tier."""
    if task in {TaskType.SELF_REFLECT, TaskType.COMPLEX_REASONING}:
        return settings.sigmaris_reflect_model or settings.openai_advanced_model
    if task is TaskType.EVAL_GENERATION:
        # Pinned to gpt-5.4-mini per an explicit operator decision (Phase
        # C-mini testset generation) — deliberately kept separate from
        # openai_nano_model so it doesn't drift if that tier's model choice
        # changes for unrelated reasons.
        return settings.eval_generation_model
    if task in {
        TaskType.ROUTING,
        TaskType.MEMORY_EXTRACTION,
        TaskType.SUMMARIZE,
        TaskType.DECISION_DETECTION,
        TaskType.EPISODE_DETECTION,
        TaskType.TOPIC_DETECTION,
        TaskType.QUERY_DECOMPOSITION,
        TaskType.MEMORY_RERANK,
        TaskType.ABSTENTION_REACTION_DETECTION,
    }:
        return settings.openai_nano_model
    return settings.openai_model


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
        task: TaskType | None = None,
    ) -> str:
        model = _openai_model_for_task(task) if task is not None else settings.openai_model
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
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
        if isinstance(backend, _OpenAIAdapter):
            return await backend.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                task=task,
            )
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
