from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.orchestrator import OrchestratorChatRequest, OrchestratorChatResponse
from app.services.orchestrator.service import run_orchestrator_chat, run_orchestrator_chat_stream

router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])
logger = logging.getLogger(__name__)

def _require_jwt(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "Authorization header with user Bearer token is required."},
        )
    jwt = authorization.removeprefix("Bearer ").strip()
    if not jwt:
        raise HTTPException(status_code=401, detail={"error": "Bearer token is empty."})
    return jwt


@router.post("/chat", response_model=OrchestratorChatResponse)
async def orchestrator_chat(
    payload: OrchestratorChatRequest,
    authorization: str | None = Header(default=None),
    x_google_access_token: str | None = Header(default=None),
    x_google_refresh_token: str | None = Header(default=None),
) -> OrchestratorChatResponse:
    jwt = _require_jwt(authorization)
    try:
        result = await run_orchestrator_chat(
            jwt=jwt,
            google_access_token=x_google_access_token,
            google_refresh_token=x_google_refresh_token,
            messages=[message.model_dump() for message in payload.messages],
            thread_id=payload.thread_id,
            request_context=payload.context,
        )
    except RuntimeError as error:
        logger.warning("orchestrator chat failed: %s", error)
        raise HTTPException(status_code=502, detail={"error": str(error)}) from error
    except Exception as error:  # noqa: BLE001
        logger.exception("orchestrator chat unexpected failure")
        raise HTTPException(status_code=500, detail={"error": str(error)}) from error

    return OrchestratorChatResponse.model_validate(result)


@router.post("/chat/stream")
async def orchestrator_chat_stream(
    payload: OrchestratorChatRequest,
    authorization: str | None = Header(default=None),
    x_google_access_token: str | None = Header(default=None),
    x_google_refresh_token: str | None = Header(default=None),
) -> StreamingResponse:
    """
    SSE streaming endpoint. Streams OpenAI deltas from the orchestrator path.

    SSE event format:
      data: {"delta": "<text chunk>"}\n\n
      data: {"done": true, "thread_id": "...", "invocation_id": "..."}\n\n
      data: {"error": "<message>"}\n\n  (on failure)
    """
    jwt = _require_jwt(authorization)

    async def _generate():
        try:
            async for event in run_orchestrator_chat_stream(
                jwt=jwt,
                google_access_token=x_google_access_token,
                google_refresh_token=x_google_refresh_token,
                messages=[message.model_dump() for message in payload.messages],
                thread_id=payload.thread_id,
                request_context=payload.context,
            ):
                if event.delta:
                    yield f"data: {json.dumps({'delta': event.delta}, ensure_ascii=False)}\n\n"
                if event.done:
                    yield (
                        f"data: {json.dumps({'done': True, 'thread_id': event.thread_id, 'invocation_id': event.invocation_id}, ensure_ascii=False)}\n\n"
                    )
                    logger.info("orchestrator stream: completed invocation=%s", event.invocation_id)
        except Exception as exc:
            logger.exception("orchestrator stream: error during generation")
            yield f"data: {json.dumps({'error': str(exc)[:300]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering for SSE
            "Connection": "keep-alive",
        },
    )
