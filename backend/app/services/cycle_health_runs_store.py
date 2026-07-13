# 役割: Phase R-3 RC指標(RC-1〜RC-5)の永続化(sigmaris_cycle_health_runs)。
#
# eval_runs_store.py(Phase C-mini/C-full)と全く同じ設計判断を踏襲した
# 別テーブル: sigmaris_decision_log/sigmaris_internal_stateと同じ
# 「service_role_only」パターン、書き込み失敗は例外を投げず記録するだけ
# (マイグレーション未適用の環境でもrun_cycle_health.py本体がクラッシュ
# しないようにするため)。

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_cycle_health_runs"


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


async def record_cycle_health_run(
    *,
    window_days: int,
    period_from: str | None,
    period_to: str | None,
    rc1: dict[str, Any],
    rc2: dict[str, Any],
    rc3: dict[str, Any],
    rc4: dict[str, Any],
    rc5: dict[str, Any],
    notes: str | None = None,
    details: dict[str, Any] | None = None,
) -> str | None:
    """1回分のRC計測実行を記録する。戻り値は新規行のid、失敗時はNone
    (例外は投げない — decision_log.log_decision()/eval_runs_store.
    record_eval_run()と同じベストエフォート方針)。

    rc1〜rc5は各cycle_health_metrics.py結果の必要フィールドのみを含む
    素のdictを渡す想定(cycle_health_runner.py側で組み立てる)。
    """
    try:
        payload: dict[str, Any] = {
            "window_days": window_days,
            "period_from": period_from,
            "period_to": period_to,
            "rc1_total_experiences": rc1.get("total_experiences"),
            "rc1_reached_count": rc1.get("reached_count"),
            "rc1_raw_completion_rate": rc1.get("raw_completion_rate"),
            "rc1_eligible_count": rc1.get("eligible_count"),
            "rc1_eligible_completion_rate": rc1.get("eligible_completion_rate"),
            "rc2_score": rc2.get("score"),
            "rc2_chat_pairs_checked": rc2.get("chat_pairs_checked"),
            "rc2_chat_order_violation_count": rc2.get("chat_order_violation_count"),
            "rc2_event_experience_checked": rc2.get("event_experience_checked"),
            "rc2_event_experience_violation_count": rc2.get("event_experience_violation_count"),
            "rc3_score": rc3.get("score"),
            "rc3_comparable_pattern_count": rc3.get("comparable_pattern_count"),
            "rc3_flip_count": rc3.get("flip_count"),
            "rc3_unsupported_flip_count": rc3.get("unsupported_flip_count"),
            "rc4_score": rc4.get("score"),
            "rc4_flags_evaluated": rc4.get("flags_evaluated"),
            "rc5_status": rc5.get("status"),
            "rc5_broke_metrics": rc5.get("broke_metrics", []),
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
            logger.info("cycle_health_runs_store: recorded run id=%s", row_id)
            return row_id
        return None
    except Exception:
        logger.exception("cycle_health_runs_store: failed to record cycle health run")
        return None


async def get_recent_cycle_health_runs(limit: int = 20) -> list[dict[str, Any]]:
    """直近の実行を新しい順に返す。失敗時は空リスト(record_cycle_health_
    run()と同じベストエフォート方針)。RC-5の履歴ベースライン算出、
    RC-3の直前スナップショット取得の両方がこれを使う。"""
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
        logger.exception("cycle_health_runs_store: failed to get_recent_cycle_health_runs")
        return []
