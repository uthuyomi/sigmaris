# 役割: Phase E-1「静的検証パイプライン」の永続化
# (sigmaris_static_verifications)。
#
# hypothesis_prioritization_store.py(Phase D-3)・hypothesis_store.py
# (Phase D-2)と同じservice_role_onlyパターンを踏襲した新規テーブル。
#
# 【設計判断】D-3のsigmaris_hypothesis_prioritiesと同じ「追記専用ログ、
# 仮説1件=1行」の設計を踏襲した。依頼書「検証結果を、D-3の
# sigmaris_hypothesis_prioritiesと紐づく形で記録する」に対応するため、
# hypothesis_priority_id(sigmaris_hypothesis_priorities.idへのソフト
# 参照)を主たる紐付けキーとし、hypothesis_id(sigmaris_hypotheses.id)
# も非正規化して併記する(joinを一切行わない設計は既存の全テーブルと
# 共通、トレーサビリティのための重複保持)。

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_static_verifications"


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


async def record_static_verification_run(
    *, run_at: str, baseline: dict[str, Any], results: list[dict[str, Any]]
) -> list[str]:
    """1回分の静的検証実行を、仮説1件=1行のバルクINSERTで記録する。
    戻り値は新規行のidのリスト、失敗時は空リスト(例外は投げない、
    既存の全storeモジュールと同じベストエフォート方針)。resultsが
    0件の場合はHTTP通信すら発生させない。"""
    if not results:
        return []
    try:
        payload = [
            {
                "run_at": run_at,
                "hypothesis_priority_id": r.get("hypothesis_priority_id"),
                "hypothesis_id": r.get("hypothesis_id"),
                "verdict": r.get("verdict"),
                "matched_modules": r.get("matched_modules") or [],
                "reason": r.get("reason") or "",
                "baseline_passed": baseline.get("passed"),
                "baseline_summary": baseline.get("summary") or "",
                "details": r.get("details") or {},
            }
            for r in results
        ]
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.post(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            json=payload,
        )
        response.raise_for_status()
        rows = response.json()
        ids = [row.get("id") for row in rows if isinstance(row, dict) and row.get("id")] if isinstance(rows, list) else []
        logger.info("static_verification_store: recorded %d verification rows", len(ids))
        return ids
    except Exception:
        logger.exception("static_verification_store: failed to record static verification run")
        return []


async def get_recent_static_verifications(*, limit: int = 50) -> list[dict[str, Any]]:
    """直近の静的検証結果を新しい順に返す(E-2以降の将来の読み取り口を
    想定して用意)。失敗時は空リスト。"""
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
        logger.exception("static_verification_store: failed to get_recent_static_verifications")
        return []
