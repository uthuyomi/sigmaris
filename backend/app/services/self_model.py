from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.services.proactive.jwt_manager import get_sigmaris_jwt
from app.services.supabase_rest import _get_client, _require_supabase_config, rest_select
from app.services.user_fact_data import build_profile_context, get_user_profile

logger = logging.getLogger(__name__)

_TABLE_MODEL = "sigmaris_self_model"
_TABLE_DISCREPANCIES = "sigmaris_self_discrepancies"
_AUDIT_TABLE = "agent_invocation_audit_logs"


def _service_headers(*, prefer_return: bool = True) -> dict[str, str]:
    base_url, _ = _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer_return:
        h["Prefer"] = "return=representation"
    return h


def _single(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Accept": "application/vnd.pgrst.object+json"}


# ─── public API ──────────────────────────────────────────────────────────────


async def get_self_model() -> dict[str, Any] | None:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    headers = _single(_service_headers(prefer_return=False))
    r = await client.get(
        f"{base_url}/rest/v1/{_TABLE_MODEL}",
        headers=headers,
        params={"limit": "1"},
    )
    if r.status_code == 406:
        return None
    r.raise_for_status()
    return r.json()


async def update_self_model(
    identity_statement: str,
    goals: list[Any],
    patterns: list[Any],
) -> dict[str, Any]:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    now = datetime.now(timezone.utc).isoformat()
    existing = await get_self_model()

    if existing is None:
        payload = {
            "version": 1,
            "identity_statement": identity_statement,
            "current_goals": goals,
            "observed_patterns": patterns,
            "belief_updates": [],
            "last_reflected_at": now,
        }
        r = await client.post(
            f"{base_url}/rest/v1/{_TABLE_MODEL}",
            headers=_single(_service_headers()),
            json=payload,
        )
    else:
        payload = {
            "version": existing["version"] + 1,
            "identity_statement": identity_statement,
            "current_goals": goals,
            "observed_patterns": patterns,
            "last_reflected_at": now,
        }
        r = await client.patch(
            f"{base_url}/rest/v1/{_TABLE_MODEL}",
            headers=_single(_service_headers()),
            params={"id": f"eq.{existing['id']}"},
            json=payload,
        )

    r.raise_for_status()
    return r.json()


async def record_discrepancy(expected: str, actual: str, note: str) -> dict[str, Any]:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    payload = {
        "expected_behavior": expected,
        "actual_behavior": actual,
        "discrepancy_note": note,
        "resolved": False,
    }
    r = await client.post(
        f"{base_url}/rest/v1/{_TABLE_DISCREPANCIES}",
        headers=_single(_service_headers()),
        json=payload,
    )
    r.raise_for_status()
    return r.json()


async def reflect() -> dict[str, Any]:
    """Analyze last 24h audit logs, then update the self model."""
    jwt = await get_sigmaris_jwt()

    # 1. Audit logs from the last 24 hours
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    logs: list[dict] = await rest_select(jwt, _AUDIT_TABLE, {
        "created_at": f"gte.{since}",
        "order": "created_at.desc",
        "limit": "50",
    }) or []

    # 2. User profile
    try:
        profile = await get_user_profile(jwt)
    except Exception:
        profile = None
    profile_ctx = build_profile_context(profile) or "ユーザープロフィール不明"

    # 3. Current self model
    current = await get_self_model()
    current_identity = current["identity_statement"] if current else ""
    current_goals = current["current_goals"] if current else []
    current_patterns = current["observed_patterns"] if current else []

    logger.info("reflect: %d audit logs, current_version=%s", len(logs), current.get("version") if current else None)

    # 4. AI analysis
    analysis = await _analyze(
        logs=logs,
        profile_ctx=profile_ctx,
        current_identity=current_identity,
        current_goals=current_goals,
        current_patterns=current_patterns,
    )

    # 5. Update self model
    updated = await update_self_model(
        identity_statement=analysis["identity_statement"],
        goals=analysis["updated_goals"],
        patterns=analysis["updated_patterns"],
    )

    # 6. Record discrepancies
    recorded = []
    for d in analysis.get("discrepancies") or []:
        try:
            rec = await record_discrepancy(
                expected=d.get("expected", ""),
                actual=d.get("actual", ""),
                note=d.get("note", ""),
            )
            recorded.append(rec)
        except Exception:
            logger.exception("Failed to record discrepancy: %s", d)

    return {
        "ok": True,
        "version": updated.get("version"),
        "audit_logs_analyzed": len(logs),
        "discrepancies_found": len(recorded),
    }


# ─── AI analysis ─────────────────────────────────────────────────────────────


def _summarize_logs(logs: list[dict]) -> str:
    if not logs:
        return "（直近24時間のログなし）"
    lines = []
    for lg in logs[:20]:
        status = lg.get("status", "?")
        caller = lg.get("caller_agent_id", "?")
        reason = (lg.get("reason") or "")[:60]
        ts = (lg.get("created_at") or "")[:16]
        dur = lg.get("duration_ms")
        dur_str = f" {dur}ms" if dur else ""
        lines.append(f"- [{ts}] {caller} → {status}{dur_str} | {reason}")
    if len(logs) > 20:
        lines.append(f"... 他 {len(logs) - 20} 件")
    return "\n".join(lines)


async def _analyze(
    *,
    logs: list[dict],
    profile_ctx: str,
    current_identity: str,
    current_goals: list,
    current_patterns: list,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    model = settings.sigmaris_reflect_model or settings.openai_model
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    log_summary = _summarize_logs(logs)

    system = (
        "あなたはシグマリス（AIアシスタント）です。"
        "自分の行動ログを分析して自己モデルを更新します。"
        "必ず有効なJSONのみを返してください。"
    )
    user = f"""{profile_ctx}

## 現在の自己認識
{current_identity or '（未設定）'}

## 現在の目標
{json.dumps(current_goals, ensure_ascii=False, indent=2)}

## 現在の観察パターン
{json.dumps(current_patterns, ensure_ascii=False, indent=2)}

## 直近24時間の行動ログ（{len(logs)}件）
{log_summary}

---
上記を踏まえて次のJSONを出力してください:
{{
  "identity_statement": "更新された自己記述（1〜3文）",
  "updated_goals": ["目標1", "目標2"],
  "updated_patterns": [
    {{"pattern": "パターン名", "frequency": "頻度", "note": "観察メモ"}}
  ],
  "discrepancies": [
    {{"expected": "予測した行動", "actual": "実際の行動", "note": "観察メモ"}}
  ]
}}
discrepanciesに相違がなければ空リスト []。"""

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=1000,
    )

    raw = response.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("reflect: AI returned invalid JSON: %s", raw[:200])
        return {
            "identity_statement": current_identity,
            "updated_goals": current_goals,
            "updated_patterns": current_patterns,
            "discrepancies": [],
        }
