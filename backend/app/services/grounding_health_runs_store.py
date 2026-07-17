# 役割: Phase G-5「Phase G継続測定」の永続化(sigmaris_grounding_health_runs)。
#
# cycle_health_runs_store.py(Phase R-3)と全く同じ設計判断を踏襲した
# 別テーブル: sigmaris_decision_log/sigmaris_citation_audit_logと同じ
# 「service_role_only」パターン、書き込み失敗は例外を投げず記録するだけ
# (マイグレーション未適用の環境でもrun_grounding_health.py本体が
# クラッシュしないようにするため)。

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_grounding_health_runs"


def _svc_headers() -> dict[str, str]:
    _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def record_grounding_health_run(
    *,
    window_days: int,
    period_from: str | None,
    period_to: str | None,
    citation_precision: dict[str, Any],
    search_trigger_rate: dict[str, Any],
    contradiction_rate: dict[str, Any],
    notes: str | None = None,
    details: dict[str, Any] | None = None,
) -> str | None:
    """1回分のGrounding-health計測実行を記録する。戻り値は新規行のid、
    失敗時はNone(例外は投げない — record_cycle_health_run()/decision_
    log.log_decision()と同じベストエフォート方針)。"""
    try:
        payload: dict[str, Any] = {
            "window_days": window_days,
            "period_from": period_from,
            "period_to": period_to,
            "citation_precision": citation_precision.get("precision"),
            "citation_precision_faithful": citation_precision.get("faithful_count"),
            "citation_precision_distorted": citation_precision.get("distorted_count"),
            "search_trigger_rate": search_trigger_rate.get("rate"),
            "search_trigger_audited_turns": search_trigger_rate.get("audited_turns"),
            "search_trigger_total_turns": search_trigger_rate.get("total_turns"),
            "contradiction_rate": contradiction_rate.get("rate"),
            "contradiction_flagged_turns": contradiction_rate.get("flagged_turns"),
            "contradiction_audited_turns": contradiction_rate.get("audited_turns"),
            "notes": notes,
            "details": details or {},
        }
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.post(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            json=payload,
        )
        response.raise_for_status()
        rows = response.json()
        if isinstance(rows, list) and rows:
            row_id = rows[0].get("id")
            logger.info("grounding_health_runs_store: recorded run id=%s", row_id)
            return row_id
        return None
    except Exception:
        logger.exception("grounding_health_runs_store: failed to record grounding health run")
        return None


async def get_recent_grounding_health_runs(limit: int = 20) -> list[dict[str, Any]]:
    """直近の実行を新しい順に返す。失敗時は空リスト(record_grounding_
    health_run()と同じベストエフォート方針)。将来トレンド表示等が必要に
    なった場合の読み取り口として、cycle_health_runs_store.get_recent_
    cycle_health_runs()と対称の形で用意した。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"order": "run_at.desc", "limit": str(limit)},
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("grounding_health_runs_store: failed to get_recent_grounding_health_runs")
        return []
