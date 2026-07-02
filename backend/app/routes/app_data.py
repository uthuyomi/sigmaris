from __future__ import annotations

# 役割: アプリ内データを扱う FastAPI HTTP ルートを定義する。

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.app_data import (
    create_chat_thread as create_chat_thread_record,
    delete_chat_thread as delete_chat_thread_record,
    get_chat_thread as get_chat_thread_record,
    get_profile_context,
    list_chat_messages as list_chat_messages_record,
    list_chat_threads as list_chat_threads_record,
    rename_chat_thread as rename_chat_thread_record,
    replace_chat_messages as replace_chat_messages_record,
    search_events as search_events_record,
)

router = APIRouter(prefix="/api/app", tags=["app-data"])


def _require_jwt(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Missing bearer token."})
    return authorization.removeprefix("Bearer ").strip()


class SearchEventsRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    fromIso: str | None = Field(default=None, max_length=64)
    toIso: str | None = Field(default=None, max_length=64)
    limit: int | None = Field(default=None, ge=1, le=50)


class ReplaceMessagesRequest(BaseModel):
    threadId: str = Field(min_length=1, max_length=80)
    messages: list[dict[str, Any]] = Field()


class CreateThreadRequest(BaseModel):
    threadId: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=80)


class RenameThreadRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@router.post("/events/search")
async def search_events(
    payload: SearchEventsRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    rows = await search_events_record(
        jwt,
        query=payload.query,
        from_iso=payload.fromIso,
        to_iso=payload.toIso,
        limit=payload.limit or 10,
    )
    return {"ok": True, "events": rows, "count": len(rows)}


@router.get("/home-context")
async def home_context(authorization: str | None = Header(default=None)):
    jwt = _require_jwt(authorization)
    context = await get_profile_context(jwt)
    return {
        "ok": True,
        "homeAddress": context["homeAddress"],
        "preferredTravelMode": context["preferredTravelMode"],
        "aiTone": context["aiTone"],
        "savedLocations": context["savedLocations"],
    }


@router.get("/chat/threads")
async def list_chat_threads(authorization: str | None = Header(default=None)):
    jwt = _require_jwt(authorization)
    threads = await list_chat_threads_record(jwt)
    return {"ok": True, "threads": threads, "count": len(threads)}


@router.post("/chat/threads")
async def create_chat_thread(
    payload: CreateThreadRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    thread = await create_chat_thread_record(
        jwt,
        thread_id=payload.threadId,
        title=payload.title,
    )
    return {"ok": True, "thread": thread}


@router.get("/chat/threads/{thread_id}")
async def get_chat_thread(thread_id: str, authorization: str | None = Header(default=None)):
    jwt = _require_jwt(authorization)
    thread = await get_chat_thread_record(jwt, thread_id)
    return {"ok": True, "thread": thread}


@router.patch("/chat/threads/{thread_id}")
async def rename_chat_thread(
    thread_id: str,
    payload: RenameThreadRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    await rename_chat_thread_record(jwt, thread_id=thread_id, title=payload.title)
    return {"ok": True}


@router.delete("/chat/threads/{thread_id}")
async def delete_chat_thread(thread_id: str, authorization: str | None = Header(default=None)):
    jwt = _require_jwt(authorization)
    await delete_chat_thread_record(jwt, thread_id=thread_id)
    return {"ok": True}


@router.get("/chat/threads/{thread_id}/messages")
async def list_chat_messages(thread_id: str, authorization: str | None = Header(default=None)):
    jwt = _require_jwt(authorization)
    messages = await list_chat_messages_record(jwt, thread_id=thread_id)
    return {"ok": True, "messages": messages, "count": len(messages)}


@router.post("/chat/messages/replace")
async def replace_chat_messages(
    payload: ReplaceMessagesRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    await replace_chat_messages_record(jwt, thread_id=payload.threadId, messages=payload.messages)
    return {"ok": True}
