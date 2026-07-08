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
    # chat_routing.py::classify_chat_intent() — a dedicated type rather than
    # reusing TaskType.ROUTING (see docs/sigmaris/
    # incident_response_latency_investigation.md 11.1 for the rationale):
    # this call is a hot-path, per-turn classification that was the subject
    # of its own multi-section latency investigation, so it gets the same
    # "one TaskType per distinct classification concern" treatment already
    # given to DECISION_DETECTION/EPISODE_DETECTION/TOPIC_DETECTION/etc.,
    # rather than folding into ROUTING's existing grab-bag of unrelated
    # one-off callers (active_inquiry.py, memory_validator.py, x_*.py).
    CHAT_INTENT_CLASSIFICATION = "chat_intent_classification"
    # Phase C-full: LLM-as-a-Judge for LongMemEval/LoCoMo public-benchmark
    # answer grading (see docs/sigmaris/phase_c_full_report.md section 3).
    # Deliberately NOT the same TaskType as EVAL_GENERATION (Phase C-mini's
    # internal-testset question generation, and this phase's own benchmark
    # answer synthesis — see bench_pipeline.py): the judge's correctness
    # verdict *is* the reported score, so a bad judgment silently invalidates
    # the whole benchmark run in a way a bad generated question or answer
    # does not (those just produce one wrong data point, still visible in
    # the per-question detail). That asymmetry — "this call's own quality is
    # the deliverable" — is the same reasoning goal_alignment.py's nuanced
    # decision-vs-goal comparison used to justify TaskType.SELF_REFLECT
    # (the advanced tier) over a cheaper classifier tier.
    EVAL_JUDGE = "eval_judge"


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
    TaskType.CHAT_INTENT_CLASSIFICATION,
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
    if task is TaskType.EVAL_JUDGE:
        # Same "sigmaris_reflect_model or openai_advanced_model" pattern as
        # SELF_REFLECT/COMPLEX_REASONING above, with its own override knob
        # (eval_judge_model) rather than sharing sigmaris_reflect_model, so
        # the operator can retune judge cost/quality independently of
        # self-reflection — relevant once a full-scale run (500+ LongMemEval
        # + ~2000 LoCoMo questions) makes the judge's per-call cost add up.
        return settings.eval_judge_model or settings.openai_advanced_model
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
        TaskType.CHAT_INTENT_CLASSIFICATION,
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
