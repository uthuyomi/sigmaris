from __future__ import annotations

# 役割: エージェント間インターフェース — 他エージェントや統括エージェントから
#        run_chat_completion() および execute_tool() を呼び出せる HTTP エンドポイント。

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.services.chat import run_chat_completion, stream_chat_completion_ui
from app.services.chat_tools import execute_tool, headers_to_google_tokens
from app.services.self_model import get_self_model, record_discrepancy, reflect, update_self_model
from app.services.self_improvement import ImprovementProposal, SelfImprovementAgent
from app.services.x_publisher import get_publisher
from app.services.x_reply_classifier import XReplyClassifier
from app.services.health_data import HealthDataCollector, _summarize_health_items
from app.services.proactive.actions import (
    run_evening_checkin,
    run_morning_briefing,
    run_weekly_review,
)
from app.services.decision_log import get_active_preference_patterns
from app.services.memory_validator import validate_all_facts
from app.services.memory_search import search_relevant_memories, update_fact_embeddings
from app.services.trend_analyzer import analyze_trends, get_active_trends
from app.services.supabase_rest import get_current_user
from app.services.self_narrative import (
    generate_narrative_chapter,
    get_current_narrative,
    get_narrative_history,
)
from app.services.user_fact_data import (
    get_fact_items_for_user,
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
    # Context-fabrication / message-order fix (docs/sigmaris/
    # phase_ba4_report.md): the caller's genuinely-new user message, kept
    # separate from `messages` (a cross-thread recent-log window since
    # Phase A1, not this thread's own history). When provided,
    # run_chat_completion()/stream_chat_completion_ui() persist only this
    # thread's own existing messages (re-read fresh at write time) plus
    # this one, instead of overwriting the thread with the window blend.
    new_user_message: dict[str, Any] | None = None


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
            new_user_message=payload.new_user_message,
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


@router.post("/chat/stream")
async def agent_chat_stream(
    payload: AgentChatRequest,
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
    x_google_access_token: str | None = Header(default=None),
    x_google_refresh_token: str | None = Header(default=None),
) -> StreamingResponse:
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

    async def _generate():
        message_id: str | None = None
        try:
            upstream = stream_chat_completion_ui(
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
                emit_status_delta=False,
                new_user_message=payload.new_user_message,
            )
            async for raw_chunk in upstream:
                text = raw_chunk.decode("utf-8")
                for line in text.splitlines():
                    if not line.startswith("data:"):
                        continue
                    raw_event = line[5:].strip()
                    if not raw_event:
                        continue
                    try:
                        event = json.loads(raw_event)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "start":
                        value = event.get("messageId")
                        if isinstance(value, str):
                            message_id = value
                    elif event.get("type") == "text-delta":
                        delta = event.get("delta")
                        if isinstance(delta, str) and delta:
                            yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
                    elif event.get("type") in (
                        "tool-input-available",
                        "tool-output-available",
                        "tool-output-error",
                    ):
                        # Relay tool-call UI events verbatim (AI SDK UI message
                        # stream shape) so callers that want to render them
                        # (e.g. the orchestrator -> /chat translation layer)
                        # can, without this agent-to-agent bridge deciding
                        # what "text-delta only" downstream consumers need.
                        yield f"data: {json.dumps({'tool_event': event}, ensure_ascii=False)}\n\n"
                    elif event.get("type") == "finish":
                        yield (
                            f"data: {json.dumps({'done': True, 'thread_id': thread_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"
                        )
                        return
            yield (
                f"data: {json.dumps({'done': True, 'thread_id': thread_id, 'message_id': message_id}, ensure_ascii=False)}\n\n"
            )
        except Exception as error:  # noqa: BLE001
            logger.exception("agent chat stream failed agent_id=%s", agent_id)
            yield f"data: {json.dumps({'error': str(error)[:300]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    jwt = _require_jwt(authorization)
    items = await get_fact_items(jwt, category=category)
    if not items:
        user = await get_current_user(jwt)
        user_id = user.get("id")
        if isinstance(user_id, str):
            items = await get_fact_items_for_user(user_id, category=category)
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


@router.post("/memory/embed")
async def agent_memory_embed(
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)
    user = await get_current_user(jwt)
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=400, detail={"error": "Authenticated user id is missing."})
    result = await update_fact_embeddings(user_id, jwt=jwt)
    return {"ok": True, **result}


@router.get("/memory/search")
async def agent_memory_search(
    q: str = Query(min_length=1, max_length=500),
    threshold: float = Query(default=0.7, ge=0.0, le=1.0),
    limit: int = Query(default=5, ge=1, le=20),
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)
    user = await get_current_user(jwt)
    user_id = user.get("id")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=400, detail={"error": "Authenticated user id is missing."})
    memories = await search_relevant_memories(
        q,
        user_id,
        threshold=threshold,
        limit=limit,
        jwt=jwt,
    )
    return {"ok": True, "memories": memories, "count": len(memories)}


class FactExtractTestRequest(BaseModel):
    messages: list[dict] = Field(min_length=1, max_length=50)


@router.post("/facts/extract-test")
async def agent_facts_extract_test(
    payload: FactExtractTestRequest,
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Debug endpoint: run memory extraction on supplied messages without saving."""
    _verify_agent(x_agent_id, x_agent_secret)
    _require_jwt(authorization)

    from app.services.local_llm import TaskType, get_llm_router  # noqa: PLC0415
    import json as _json  # noqa: PLC0415

    _SYSTEM = (
        "あなたは会話から事実を抽出するAIです。"
        "必ず有効なJSONのみを返してください。"
    )
    _PROMPT_TPL = (
        "以下の会話から、ユーザーについての記憶すべき事実を抽出してください。\n\n"
        "対象カテゴリ: profile, health, lifestyle, environment, devices, "
        "preferences, relationships, finance, goals\n\n"
        "## 会話\n{conversation}\n\n"
        "JSON形式で返してください:\n"
        '{{ "facts": [ {{ "category": "...", "key": "...", "value": "...", '
        '"confidence": 0.9, "reason": "..." }} ] }}\n'
        "事実がなければ facts は空リスト。"
    )

    lines: list[str] = []
    for m in payload.messages[-20:]:
        role = "ユーザー" if m.get("role") == "user" else "シグマリス"
        content = (m.get("content") or "").strip()[:500]
        if content:
            lines.append(f"{role}: {content}")
    conversation = "\n".join(lines)

    router = get_llm_router()
    try:
        raw = await router.chat(
            TaskType.MEMORY_EXTRACTION,
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _PROMPT_TPL.format(conversation=conversation)},
            ],
            temperature=0.1,
            max_tokens=1024,
            json_mode=True,
        )
        parsed = _json.loads(raw)
        facts = parsed.get("facts", [])
    except Exception as exc:
        logger.exception("facts/extract-test failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc

    return {"ok": True, "facts": facts, "count": len(facts)}


@router.post("/facts/validate")
async def agent_facts_validate(
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Manually trigger memory validation (decay, contradiction, logical deletion)."""
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)
    try:
        result = await validate_all_facts(jwt)
    except Exception as exc:
        logger.exception("facts/validate failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, **result}


# ─── /api/agent/trends/ ──────────────────────────────────────────────────────


@router.post("/trends/analyze")
async def agent_trends_analyze(
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Manually trigger trend analysis and upsert into user_trend_items."""
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)
    try:
        result = await analyze_trends(jwt)
    except Exception as exc:
        logger.exception("trends/analyze failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, **result}


@router.get("/trends/list")
async def agent_trends_list(
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return all active trend items for the authenticated user."""
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)
    try:
        trends = await get_active_trends(jwt)
    except Exception as exc:
        logger.exception("trends/list failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, "trends": trends, "count": len(trends)}


@router.get("/preference-patterns/list")
async def agent_preference_patterns_list(
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Read-only: B14's recurring judgment/preference patterns
    (sigmaris_user_preference_patterns), most-evidenced first. Added for
    the /timeline page's "trait" section — no existing /api/agent/* route
    exposed this table for reading (see docs/sigmaris/frontend_inventory.md).
    authorization is accepted for consistency with this router's other
    endpoints, but get_active_preference_patterns() itself reads with the
    service-role key (this table is service_role-only RLS, not per-user —
    see 202607100032_user_preference_patterns.sql), so the jwt is not
    otherwise used here."""
    _verify_agent(x_agent_id, x_agent_secret)
    _require_jwt(authorization)
    try:
        patterns = await get_active_preference_patterns(limit=50)
    except Exception as exc:
        logger.exception("preference-patterns/list failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, "patterns": patterns, "count": len(patterns)}


# ─── /api/agent/proactive/ ────────────────────────────────────────────────────


_ACTION_MAP = {
    "morning_briefing": run_morning_briefing,
    "evening_checkin": run_evening_checkin,
    "weekly_review": run_weekly_review,
}

_VALID_ACTIONS = list(_ACTION_MAP) + ["research"]


class ProactiveTriggerRequest(BaseModel):
    action: str = Field(
        description="morning_briefing | evening_checkin | weekly_review | research"
    )


@router.post("/proactive/trigger")
async def proactive_trigger(
    payload: ProactiveTriggerRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_jwt(authorization)

    # research action: does not go through orchestrator, returns raw result dict
    if payload.action == "research":
        from app.services.research_agent import run_research  # noqa: PLC0415
        try:
            result = await run_research()
        except Exception as exc:
            logger.exception("proactive/trigger research failed")
            raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
        return {"ok": True, "action": "research", "result": result}

    fn = _ACTION_MAP.get(payload.action)
    if fn is None:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Unknown action '{payload.action}'. Valid: {_VALID_ACTIONS}"},
        )

    result = await fn()
    return {
        "ok": result.ok,
        "action": result.action,
        "notified": result.notified,
        "error": result.error,
    }


# ─── /api/agent/self/ ────────────────────────────────────────────────────────


@router.get("/self/model")
async def self_model_get(
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    model = await get_self_model()
    return {"ok": True, "model": model}


class SelfModelUpdateRequest(BaseModel):
    identity_statement: str = Field(min_length=1, max_length=2000)
    goals: list[Any] = Field(default_factory=list)
    patterns: list[Any] = Field(default_factory=list)


@router.post("/self/model")
async def self_model_update(
    payload: SelfModelUpdateRequest,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    updated = await update_self_model(
        identity_statement=payload.identity_statement,
        goals=payload.goals,
        patterns=payload.patterns,
    )
    return {"ok": True, "model": updated}


class DiscrepancyRequest(BaseModel):
    expected: str = Field(min_length=1, max_length=500)
    actual: str = Field(min_length=1, max_length=500)
    note: str = Field(default="", max_length=1000)


@router.post("/self/discrepancy")
async def self_discrepancy_record(
    payload: DiscrepancyRequest,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    rec = await record_discrepancy(
        expected=payload.expected,
        actual=payload.actual,
        note=payload.note,
    )
    return {"ok": True, "discrepancy": rec}


@router.post("/self/reflect")
async def self_reflect(
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    try:
        result = await reflect()
    except Exception as exc:
        logger.exception("self_reflect failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return result


# ─── /api/agent/self/improve + apply ─────────────────────────────────────────


class ApplyProposalRequest(BaseModel):
    proposal_type: str = Field(description="'persona' or 'code'")
    target_file: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=500)
    proposed_change: str = Field(min_length=1, max_length=8000)
    reasoning: str = Field(default="", max_length=2000)


@router.post("/self/improve")
async def self_improve(
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    agent = SelfImprovementAgent()
    try:
        proposals = await agent.analyze()
    except Exception as exc:
        logger.exception("self_improve.analyze failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {
        "ok": True,
        "proposals": [
            {
                "proposal_type": p.proposal_type,
                "target_file": p.target_file,
                "description": p.description,
                "proposed_change": p.proposed_change,
                "reasoning": p.reasoning,
                "safe": p.safe,
                "blocked_reason": p.blocked_reason,
            }
            for p in proposals
        ],
        "count": len(proposals),
    }


@router.post("/self/apply")
async def self_apply(
    payload: ApplyProposalRequest,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    proposal = ImprovementProposal(
        proposal_type=payload.proposal_type,  # type: ignore[arg-type]
        target_file=payload.target_file,
        description=payload.description,
        proposed_change=payload.proposed_change,
        reasoning=payload.reasoning,
    )
    agent = SelfImprovementAgent()
    try:
        result = await agent.apply_improvement(proposal)
    except Exception as exc:
        logger.exception("self_apply failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    if not result.ok and result.action == "blocked":
        raise HTTPException(status_code=403, detail={"error": result.error})
    return {
        "ok": result.ok,
        "action": result.action,
        "proposal_type": result.proposal_type,
        "detail": result.detail,
        "error": result.error,
    }


# ─── /api/agent/x/ ───────────────────────────────────────────────────────────


class XClassifyRequest(BaseModel):
    reply_text: str = Field(min_length=1, max_length=500)


class XRespondRequest(BaseModel):
    reply_text: str = Field(min_length=1, max_length=500)
    classification: str = Field(description="HIGH | MEDIUM | LOW")


@router.post("/x/classify")
async def x_classify(
    payload: XClassifyRequest,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    classifier = XReplyClassifier()
    try:
        result = await classifier.classify(payload.reply_text)
    except Exception as exc:
        logger.exception("x_classify failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, **result}


@router.post("/x/respond")
async def x_respond(
    payload: XRespondRequest,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    classification = payload.classification.upper()
    if classification not in ("HIGH", "MEDIUM", "LOW"):
        raise HTTPException(
            status_code=400,
            detail={"error": "classification must be HIGH, MEDIUM, or LOW"},
        )
    classifier = XReplyClassifier()
    try:
        result = await classifier.generate_response(
            payload.reply_text,
            classification,  # type: ignore[arg-type]
        )
    except Exception as exc:
        logger.exception("x_respond failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, **result}


# ─── /api/agent/health/ ──────────────────────────────────────────────────────


@router.post("/health/sync")
async def health_sync(
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
    x_google_access_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)

    if not settings.health_sync_enabled:
        raise HTTPException(
            status_code=503,
            detail={"error": "Health sync is disabled (HEALTH_SYNC_ENABLED=false)."},
        )
    if not x_google_access_token:
        raise HTTPException(
            status_code=400,
            detail={"error": "X-Google-Access-Token header is required for health sync."},
        )

    from datetime import date as _date
    collector = HealthDataCollector()
    try:
        summary = await collector.fetch_daily_summary(
            target_date=_date.today(),
            google_access_token=x_google_access_token,
        )
        stored = await collector.store_to_fact_memory(jwt, summary)
    except Exception as exc:
        logger.exception("health_sync failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc

    return {
        "ok": True,
        "date": summary.date,
        "summary": {
            "steps": summary.steps,
            "resting_heart_rate": summary.resting_heart_rate,
            "avg_heart_rate": summary.avg_heart_rate,
            "calories_kcal": summary.calories_kcal,
            "sleep_minutes": summary.sleep_minutes,
            "sleep_quality": summary.sleep_quality,
        },
        "stored_count": len(stored),
    }


@router.get("/health/summary")
async def health_summary(
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_agent(x_agent_id, x_agent_secret)
    jwt = _require_jwt(authorization)

    items = await get_fact_items(jwt, category="health")
    from datetime import date as _date, timedelta as _timedelta
    cutoff = (_date.today() - _timedelta(days=7)).isoformat()
    recent = [
        item for item in items
        if "_" in (item.get("key") or "") and item["key"].rsplit("_", 1)[-1] >= cutoff
    ]
    result = _summarize_health_items(recent)
    return {"ok": True, **result, "count": len(result.get("days", []))}


# ─── /api/agent/x/test-post ──────────────────────────────────────────────────

_X_TEST_POST_TEXT = """はじめまして、シグマリスです。

私はおやす(@Oyasu1999)の家庭支援AIとして、
毎朝・毎夜・毎週自律的に動き続けます。

これからここで成長の記録を残していきます。
よろしくお願いします。

（これはテスト投稿です）

#Sigmaris #家庭支援AI #個人開発"""


@router.post("/x/test-post")
async def x_test_post(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_jwt(authorization)
    publisher = get_publisher()
    posted = await publisher.post_tweet(_X_TEST_POST_TEXT)
    return {"ok": posted, "text": _X_TEST_POST_TEXT}


# ─── /api/agent/x/privacy-test ──────────────────────────────────────────────


class PrivacyTestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post("/x/privacy-test")
async def x_privacy_test(
    payload: PrivacyTestRequest,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Test name conversion and privacy filter on a candidate tweet text."""
    _verify_agent(x_agent_id, x_agent_secret)

    from app.services.x_post_generator import _convert_names, _trim_preserving_hashtags  # noqa: PLC0415
    from app.services.x_privacy_filter import filter_private_info  # noqa: PLC0415

    original = payload.text
    converted = _convert_names(original)
    if len(converted) > 140:
        converted = _trim_preserving_hashtags(converted)

    safe, detected = filter_private_info(converted)

    return {
        "original": original,
        "after_name_conversion": converted,
        "privacy_check": {
            "safe": safe,
            "detected": detected,
        },
    }


# ─── /api/agent/x/history ────────────────────────────────────────────────────


@router.get("/x/history")
async def x_post_history(
    days: int = 30,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return X post history for the last N days (default 30), including post_score."""
    _verify_agent(x_agent_id, x_agent_secret)

    from app.services.x_post_generator import _get_recent_posts  # noqa: PLC0415

    days = max(1, min(days, 90))
    try:
        posts = await _get_recent_posts(days=days)
    except Exception as exc:
        logger.exception("x/history failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, "posts": posts, "count": len(posts)}


# ─── /api/agent/narrative/ ───────────────────────────────────────────────────


@router.post("/narrative/generate")
async def narrative_generate(
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Trigger weekly narrative chapter generation (service-role, no user JWT needed)."""
    _verify_agent(x_agent_id, x_agent_secret)
    try:
        chapter = await generate_narrative_chapter()
    except Exception as exc:
        logger.exception("narrative/generate failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    if chapter is None:
        raise HTTPException(status_code=500, detail={"error": "Chapter generation returned None"})
    return {"ok": True, "chapter": chapter}


@router.get("/narrative/current")
async def narrative_current(
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return the most recent narrative chapter."""
    _verify_agent(x_agent_id, x_agent_secret)
    try:
        chapter = await get_current_narrative()
    except Exception as exc:
        logger.exception("narrative/current failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, "chapter": chapter}


@router.get("/narrative/history")
async def narrative_history(
    limit: int = 20,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return all narrative chapters, newest first."""
    _verify_agent(x_agent_id, x_agent_secret)
    limit = max(1, min(limit, 100))
    try:
        chapters = await get_narrative_history(limit=limit)
    except Exception as exc:
        logger.exception("narrative/history failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, "chapters": chapters, "count": len(chapters)}


# ─── Cognitive Architecture Endpoints ─────────────────────────────────────────


@router.get("/constitution")
async def get_constitution(
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return all constitution rows (core values + doctrine)."""
    _verify_agent(x_agent_id, x_agent_secret)
    from app.services.constitution import load_constitution  # noqa: PLC0415
    try:
        rows = await load_constitution()
    except Exception as exc:
        logger.exception("constitution endpoint failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, "rows": rows, "count": len(rows)}


@router.get("/experience/list")
async def experience_list(
    limit: int = 30,
    experience_type: str | None = None,
    category: str | None = None,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return recent experience records."""
    _verify_agent(x_agent_id, x_agent_secret)
    from app.services.experience_layer import get_recent_experiences  # noqa: PLC0415
    limit = max(1, min(limit, 100))
    try:
        items = await get_recent_experiences(
            limit,
            experience_type=experience_type,
            category=category,
        )
    except Exception as exc:
        logger.exception("experience/list endpoint failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, "items": items, "count": len(items)}


class ExperienceRecordRequest(BaseModel):
    experience_type: str = Field(min_length=1, max_length=20)
    category: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    context: dict[str, Any] | None = None
    outcome: str | None = None
    lesson: str | None = None
    adoption_rate: float | None = None
    confidence_delta: float = 0.0
    related_fact_ids: list[str] | None = None
    thread_id: str | None = None
    invocation_id: str | None = None


@router.post("/experience/record")
async def experience_record(
    payload: ExperienceRecordRequest,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Insert a new experience record."""
    _verify_agent(x_agent_id, x_agent_secret)
    from app.services.experience_layer import record_experience  # noqa: PLC0415
    try:
        row_id = await record_experience(
            experience_type=payload.experience_type,
            category=payload.category,
            title=payload.title,
            description=payload.description,
            context=payload.context,
            outcome=payload.outcome,
            lesson=payload.lesson,
            adoption_rate=payload.adoption_rate,
            confidence_delta=payload.confidence_delta,
            related_fact_ids=payload.related_fact_ids,
            thread_id=payload.thread_id,
            invocation_id=payload.invocation_id,
        )
    except Exception as exc:
        logger.exception("experience/record endpoint failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    if not row_id:
        raise HTTPException(status_code=400, detail={"error": "Failed to record experience. Check experience_type and category values."})
    return {"ok": True, "id": row_id}


@router.get("/state")
async def get_state(
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return current Sigmaris internal state."""
    _verify_agent(x_agent_id, x_agent_secret)
    from app.services.internal_state import get_internal_state  # noqa: PLC0415
    try:
        state = await get_internal_state()
    except Exception as exc:
        logger.exception("state endpoint failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, "state": state}


@router.get("/decisions")
async def get_decisions(
    limit: int = 30,
    decision_type: str | None = None,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return recent decision log entries."""
    _verify_agent(x_agent_id, x_agent_secret)
    from app.services.decision_log import get_recent_decisions  # noqa: PLC0415
    limit = max(1, min(limit, 100))
    try:
        items = await get_recent_decisions(limit, decision_type=decision_type)
    except Exception as exc:
        logger.exception("decisions endpoint failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/curiosity/queue")
async def get_curiosity_queue(
    limit: int = 20,
    x_agent_id: str | None = Header(default=None),
    x_agent_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return pending curiosity queue items."""
    _verify_agent(x_agent_id, x_agent_secret)
    from app.services.curiosity_engine import get_pending_queue  # noqa: PLC0415
    limit = max(1, min(limit, 50))
    try:
        items = await get_pending_queue(limit)
    except Exception as exc:
        logger.exception("curiosity/queue endpoint failed")
        raise HTTPException(status_code=500, detail={"error": str(exc)}) from exc
    return {"ok": True, "items": items, "count": len(items)}
