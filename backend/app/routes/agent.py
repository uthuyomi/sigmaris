from __future__ import annotations

# 役割: エージェント間インターフェース — 他エージェントや統括エージェントから
#        run_chat_completion() および execute_tool() を呼び出せる HTTP エンドポイント。

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.chat import run_chat_completion
from app.services.chat_tools import execute_tool, headers_to_google_tokens
from app.services.proactive.actions import (
    run_evening_checkin,
    run_morning_briefing,
    run_weekly_review,
)
from app.services.user_fact_data import (
    get_fact_items,
    get_null_fields,
    get_user_profile,
    upsert_fact_item,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])
logger = logging.getLogger(__name__)


def _parse_agent_secrets() -> dict[str, str]:
    raw = settings.agent_secrets
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _verify_agent(agent_id: str | None, agent_secret: str | None) -> str:
    secrets = _parse_agent_secrets()
    if not secrets:
        raise HTTPException(
            status_code=503,
            detail={"error": "Agent interface is not configured (AGENT_SECRETS not set)."},
        )
    if not agent_id or not agent_secret:
        raise HTTPException(
            status_code=401,
            detail={"error": "X-Agent-ID and X-Agent-Secret headers are required."},
        )
    expected = secrets.get(agent_id)
    if not expected or expected != agent_secret:
        raise HTTPException(
            status_code=403,
            detail={"error": "Invalid agent credentials."},
        )
    return agent_id


def _require_jwt(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "Authorization header with user Bearer token is required."},
        )
    return authorization.removeprefix("Bearer ").strip()


class AgentChatRequest(BaseModel):
    thread_id: str | None = Field(default=None, max_length=80)
    messages: list[dict] = Field(max_length=50)
    system_override: str | None = Field(default=None, max_length=4000)
    persist_thread: bool = False
    context: dict[str, Any] | None = None


class AgentToolRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    audit: dict[str, str | None] | None = None


@router.post("/chat/complete")
async def agent_chat_complete(
    payload: AgentChatRequest,
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
    x_google_access_token: str | None = Header(default=None),
    x_google_refresh_token: str | None = Header(default=None),
) -> dict[str, Any]:
    agent_id = _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)

    thread_id = payload.thread_id or str(uuid.uuid4())
    persist = payload.persist_thread and payload.thread_id is not None

    reason = (payload.context or {}).get("reason") if payload.context else None
    audit_info: dict[str, str | None] = {
        "actor_type": "agent",
        "actor_ref": agent_id,
        "reason": reason,
    }

    try:
        final_text, _, message_id = await run_chat_completion(
            jwt=jwt,
            google_header_map={
                "x-google-access-token": x_google_access_token or "",
                "x-google-refresh-token": x_google_refresh_token or "",
            },
            thread_id=thread_id,
            messages=payload.messages,
            system=payload.system_override,
            persist_messages=persist,
            audit_info=audit_info,
        )
    except RuntimeError as error:
        logger.warning("agent chat complete error agent_id=%s error=%s", agent_id, error)
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
    except Exception as error:  # noqa: BLE001
        logger.exception("agent chat complete unexpected error agent_id=%s", agent_id)
        raise HTTPException(status_code=500, detail={"error": str(error)}) from error

    return {
        "ok": True,
        "text": final_text,
        "message_id": message_id,
        "thread_id": thread_id,
    }


@router.post("/tools/execute")
async def agent_tools_execute(
    payload: AgentToolRequest,
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
    x_google_access_token: str | None = Header(default=None),
    x_google_refresh_token: str | None = Header(default=None),
) -> dict[str, Any]:
    agent_id = _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)

    audit_reason = (payload.audit or {}).get("reason")
    audit_info: dict[str, str | None] = {
        "actor_type": "agent",
        "actor_ref": agent_id,
        "reason": audit_reason,
    }

    google_tokens = headers_to_google_tokens({
        "x-google-access-token": x_google_access_token or "",
        "x-google-refresh-token": x_google_refresh_token or "",
    })

    try:
        result = await execute_tool(
            jwt=jwt,
            google_tokens=google_tokens,
            name=payload.tool,
            arguments=payload.arguments,
            audit_info=audit_info,
        )
    except Exception as error:  # noqa: BLE001
        logger.exception(
            "agent tool execute failed agent_id=%s tool=%s", agent_id, payload.tool
        )
        raise HTTPException(status_code=500, detail={"error": str(error)}) from error

    return {"ok": True, "result": result}


# ─── /api/agent/facts/ ────────────────────────────────────────────────────────


class FactItemUpsertRequest(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    key: str = Field(min_length=1, max_length=100)
    value: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = Field(default="manual", max_length=20)
    reason: str = Field(default="", max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    expires_at: str | None = None


@router.get("/facts/profile")
async def agent_facts_profile(
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)
    profile = await get_user_profile(jwt)
    return {"ok": True, "profile": profile}


@router.get("/facts/items")
async def agent_facts_items(
    category: str | None = None,
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)
    items = await get_fact_items(jwt, category=category)
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/facts/items")
async def agent_facts_upsert(
    payload: FactItemUpsertRequest,
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)
    result = await upsert_fact_item(
        jwt,
        category=payload.category,
        key=payload.key,
        value=payload.value,
        confidence=payload.confidence,
        source=payload.source,
        reason=payload.reason,
        notes=payload.notes,
        expires_at=payload.expires_at,
    )
    return {"ok": True, "result": result}


@router.get("/facts/unknown")
async def agent_facts_unknown(
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)
    missing = await get_null_fields(jwt)
    return {"ok": True, "unknown": missing, "count": len(missing)}


# ─── /api/agent/proactive/ ────────────────────────────────────────────────────


_ACTION_MAP = {
    "morning_briefing": run_morning_briefing,
    "evening_checkin": run_evening_checkin,
    "weekly_review": run_weekly_review,
}


class ProactiveTriggerRequest(BaseModel):
    action: str = Field(description="morning_briefing | evening_checkin | weekly_review")


@router.post("/proactive/trigger")
async def proactive_trigger(
    payload: ProactiveTriggerRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_jwt(authorization)

    fn = _ACTION_MAP.get(payload.action)
    if fn is None:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Unknown action '{payload.action}'. Valid: {list(_ACTION_MAP)}"},
        )

    result = await fn()
    return {
        "ok": result.ok,
        "action": result.action,
        "notified": result.notified,
        "error": result.error,
    }
