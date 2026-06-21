from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.supabase_rest import rest_insert, rest_update

TABLE = "agent_invocation_audit_logs"


async def start_invocation(
    *,
    jwt: str,
    invocation_id: str,
    user_id: str,
    caller_agent_id: str,
    target_agent_id: str,
    target_endpoint: str,
    reason: str,
    request_summary: dict[str, Any],
    persona_version: str,
    persona_hash: str,
) -> dict[str, Any]:
    row = await rest_insert(
        jwt,
        TABLE,
        {
            "invocation_id": invocation_id,
            "user_id": user_id,
            "caller_agent_id": caller_agent_id,
            "target_agent_id": target_agent_id,
            "target_endpoint": target_endpoint,
            "reason": reason,
            "status": "started",
            "request_summary": request_summary,
            "persona_version": persona_version,
            "persona_hash": persona_hash,
        },
        single=True,
    )
    if not isinstance(row, dict) or not row.get("id"):
        raise RuntimeError("Invocation audit start did not return a persisted row.")
    return row


async def finish_invocation(
    *,
    jwt: str,
    audit_row_id: str,
    status: str,
    response_summary: dict[str, Any] | None,
    error_code: str | None,
    duration_ms: int,
) -> None:
    rows = await rest_update(
        jwt,
        TABLE,
        {
            "status": status,
            "response_summary": response_summary,
            "error_code": error_code,
            "duration_ms": duration_ms,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
        {"id": f"eq.{audit_row_id}"},
    )
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError("Invocation audit completion update was not persisted.")
