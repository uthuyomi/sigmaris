from __future__ import annotations

# 役割: Phase D〜H(自己改良システム、未実装)向け、SB-7
# (improvement_cycle_gain)の記録基盤。
#
# 【重要】このファイルにはPhase D以降の「改善サイクル」を実際に呼び出す
# コードは含まれていない(呼び出し先がまだ存在しないため — 指示書要件2)。
# record_improvement_cycle()/get_recent_improvement_cycles()は、Phase D
# の改良提案エンジンが実装された際、「変更を適用する前後でC-mini/SB-3の
# 各指標を測定し、compute_improvement_cycle_gain()(improvement_cycle_
# metrics.py)で伸び率を算出し、この関数で記録する」という形でそのまま
# 呼び出される想定の、土台のみ。
#
# sigmaris_eval_runs/sigmaris_bench_runsと同じ「service_role専用RLS」
# 「書き込み失敗は例外を投げず記録するだけ」パターンを踏襲する。

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_improvement_cycles"


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


async def record_improvement_cycle(
    *,
    cycle_label: str,
    change_description: str,
    before_metrics: dict[str, float | None],
    after_metrics: dict[str, float | None],
    overall_gain_pct: float,
    metric_gains: list[dict[str, Any]],
    skipped_metrics: list[str] | None = None,
    notes: str | None = None,
) -> str | None:
    """Insert one improvement-cycle record. Returns the new row id, or None
    if persistence failed (migration not applied, or
    SUPABASE_SERVICE_ROLE_KEY not configured) — never raises, matching
    eval_runs_store.record_eval_run()/bench_runs_store.record_bench_run()'s
    best-effort semantics.

    cycle_label/change_description are free text describing what the cycle
    changed (e.g. cycle_label="B7 decompose_query prompt v2",
    change_description="tightened the multi-hop detection threshold").
    before_metrics/after_metrics are expected to be the same shape
    improvement_cycle_metrics.compute_improvement_cycle_gain() takes/
    produces gains from — this function does not itself call that pure
    function; the caller (future Phase D code) is expected to call it and
    pass the results in here, keeping this module I/O-only.
    """
    try:
        payload: dict[str, Any] = {
            "cycle_label": cycle_label,
            "change_description": change_description,
            "before_metrics": before_metrics,
            "after_metrics": after_metrics,
            "overall_gain_pct": overall_gain_pct,
            "metric_gains": metric_gains,
            "skipped_metrics": skipped_metrics or [],
            "notes": notes,
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
            logger.info("improvement_cycle_store: recorded cycle id=%s label=%s", row_id, cycle_label)
            return row_id
        return None
    except Exception:
        logger.exception("improvement_cycle_store: failed to record improvement cycle")
        return None


async def get_recent_improvement_cycles(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent improvement-cycle records, newest first.
    Empty list on any failure (mirrors record_improvement_cycle's
    best-effort semantics)."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"order": "recorded_at.desc", "limit": str(limit)},
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("improvement_cycle_store: failed to get_recent_improvement_cycles")
        return []
