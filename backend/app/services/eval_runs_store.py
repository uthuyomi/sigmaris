# 役割: Phase C-mini評価結果(sigmaris_eval_runs)の永続化。
#
# sigmaris_decision_log/sigmaris_internal_stateと同じ「service_role_only」パターン
# (メタ/運用データであり、ユーザー所有コンテンツではないためRLSはuser_idスコープ
# ではなくservice_role専用)。マイグレーション(202607060028)未適用の環境でも
# run_eval.py本体がクラッシュしないよう、書き込み失敗は例外を投げず記録するだけ
# にしている(スコアの標準出力表示はこの関数の成否に依存しない設計、
# scripts/run_eval.py参照)。

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_eval_runs"


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


async def record_eval_run(
    *,
    testset_version: str | None,
    testset_size: int,
    memory_precision: float,
    memory_recall: float,
    memory_f1_score: float,
    rag_ndcg_score: float,
    response_error_rate: float | None,
    response_sample_size: int | None,
    memory_duplicate_rate: float | None = None,
    duplicate_fact_count: int | None = None,
    duplicate_cluster_count: int | None = None,
    notes: str | None = None,
    details: dict[str, Any] | None = None,
) -> str | None:
    """Insert one eval run row. Returns the new row id, or None if
    persistence failed (e.g. migration not applied yet, or
    SUPABASE_SERVICE_ROLE_KEY not configured) — never raises, matching the
    "best-effort logging" pattern used by decision_log.log_decision().

    memory_duplicate_rate/duplicate_fact_count/duplicate_cluster_count
    (Phase C-full-2, SB-3) default to None so existing callers keep working
    unchanged. If migration 202607210043_sigmaris_eval_runs_sb3.sql hasn't
    been applied yet, PostgREST rejects the POST outright (unknown
    columns) and this whole function falls back to its normal
    already-established None-return path below — the same degrade-safely
    behavior every other not-yet-applied-migration scenario in this
    codebase already has, not a new failure mode this change introduces.
    """
    try:
        payload: dict[str, Any] = {
            "testset_version": testset_version,
            "testset_size": testset_size,
            "memory_precision": memory_precision,
            "memory_recall": memory_recall,
            "memory_f1_score": memory_f1_score,
            "rag_ndcg_score": rag_ndcg_score,
            "response_error_rate": response_error_rate,
            "response_sample_size": response_sample_size,
            "memory_duplicate_rate": memory_duplicate_rate,
            "duplicate_fact_count": duplicate_fact_count,
            "duplicate_cluster_count": duplicate_cluster_count,
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
            logger.info("eval_runs_store: recorded run id=%s", row_id)
            return row_id
        return None
    except Exception:
        logger.exception("eval_runs_store: failed to record eval run")
        return None


async def get_recent_eval_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent eval runs, newest first. Empty list on any
    failure (mirrors record_eval_run's best-effort semantics)."""
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
        logger.exception("eval_runs_store: failed to get_recent_eval_runs")
        return []
