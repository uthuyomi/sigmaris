# 役割: チャット応答とストリーミングの FastAPI HTTP ルートを定義する。

import json

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import logging

from app.services.chat import stream_chat_completion_ui

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


class ChatStreamRequest(BaseModel):
    messages: list[dict] = Field()
    system: str | None = Field(default=None, max_length=4000)
    threadId: str = Field(min_length=1, max_length=80)


def _require_jwt(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Missing bearer token."})
    return authorization.removeprefix("Bearer ").strip()


@router.get("/capabilities")
async def chat_capabilities():
    return {
        "ok": True,
        "backendTools": [
            "chat.stream",
            "chat.router",
            "google.calendar",
            "google.sheets",
            "mobility.plan",
            "import.preview",
            "app.events.search",
            "app.home-context",
            "app.chat.messages.replace",
        ],
        "notes": [
            "OpenAI stream generation runs in backend.",
            "Frontend /api/chat should only proxy the SSE stream.",
            "Requests are classified before tool selection and final LLM generation.",
        ],
    }


@router.post("/stream")
async def chat_stream(
    payload: ChatStreamRequest,
    authorization: str | None = Header(default=None),
    x_google_access_token: str | None = Header(default=None),
    x_google_refresh_token: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)

    try:
        stream = stream_chat_completion_ui(
            jwt=jwt,
            google_header_map={
                "x-google-access-token": x_google_access_token or "",
                "x-google-refresh-token": x_google_refresh_token or "",
            },
            thread_id=payload.threadId,
            messages=payload.messages,
            system=None,
        )
    except RuntimeError as error:
        logger.exception("chat stream runtime error")
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
    except Exception as error:  # noqa: BLE001
        logger.exception("chat stream unexpected error")
        raise HTTPException(status_code=500, detail={"error": str(error)}) from error

    async def safe_stream():
        try:
            async for chunk in stream:
                yield chunk
        except Exception as error:  # noqa: BLE001
            logger.exception("chat stream body failed")
            text_part_id = "backend-error"
            fallback_events = (
                {"type": "text-start", "id": text_part_id},
                {
                    "type": "text-delta",
                    "id": text_part_id,
                    "delta": f"処理中に接続が落ちたよ。backend 側で例外が出ているから、直前のログを見れば原因が分かるはずだね。詳細: {error}",
                },
                {"type": "text-end", "id": text_part_id},
                {"type": "finish", "finishReason": "error"},
            )
            for event in fallback_events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")

    return StreamingResponse(
        safe_stream(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-vercel-ai-ui-message-stream": "v1",
            "x-accel-buffering": "no",
        },
    )
