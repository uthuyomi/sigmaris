from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException

from app.schemas.orchestrator import OrchestratorChatRequest, OrchestratorChatResponse
from app.services.orchestrator.service import run_orchestrator_chat

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
