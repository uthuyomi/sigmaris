# 役割: Phase D-1「根拠収集」の永続化(sigmaris_evidence_bundles)。
#
# grounding_health_runs_store.py(Phase G-5)・cycle_health_runs_store.py
# (Phase R-3)と全く同じ設計判断を踏襲した別テーブル: service_role_only
# パターン、書き込み失敗は例外を投げず記録するだけ(マイグレーション
# 未適用の環境でもrun_evidence_aggregation.py本体がクラッシュしない
# ようにするため)。
#
# 【設計判断】D-1自身の出力(集約済みの根拠一覧)は、Phase R/Gのような
# 「既存データから指標を再計算する」性質ではなく「既存データを読み集約
# した結果そのもの」であり、新しいテレメトリの収集ではない。次タスク
# (D-2、仮説生成)がこのテーブルをそのまま読み取り口として使えるように、
# Phase R/Gと同じ「1回の実行=1行」の永続化テーブルとして設計した
# (依頼書「出力形式: JSON、または専用のテーブル」の後者を採用した判断
# 根拠、レポート参照)。

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_evidence_bundles"


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


async def record_evidence_bundle(
    *,
    run_at: str,
    limit: int,
    sources_checked: dict[str, Any],
    category_counts: dict[str, Any],
    items: list[dict[str, Any]],
    notes: str | None = None,
) -> str | None:
    """1回分の根拠収集実行を記録する。戻り値は新規行のid、失敗時はNone
    (例外は投げない — record_grounding_health_run()/record_cycle_health_
    run()と同じベストエフォート方針)。"""
    try:
        payload: dict[str, Any] = {
            "run_at": run_at,
            "item_limit": limit,
            "phase_r_runs_checked": sources_checked.get("phase_r_runs"),
            "phase_g_runs_checked": sources_checked.get("phase_g_runs"),
            "mastery_proposals_checked": sources_checked.get("mastery_proposals"),
            "bug_inventory_rows_checked": sources_checked.get("bug_inventory_rows"),
            "metric_degradation_count": category_counts.get("metric_degradation", 0),
            "recurring_problem_count": category_counts.get("recurring_problem", 0),
            "mastery_proposal_count": category_counts.get("mastery_proposal", 0),
            "items": items,
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
            logger.info("evidence_aggregation_store: recorded bundle id=%s", row_id)
            return row_id
        return None
    except Exception:
        logger.exception("evidence_aggregation_store: failed to record evidence bundle")
        return None


async def get_recent_evidence_bundles(limit: int = 20) -> list[dict[str, Any]]:
    """直近の実行を新しい順に返す。失敗時は空リスト(record_evidence_
    bundle()と同じベストエフォート方針)。D-2(仮説生成、未実装)が最新の
    根拠一覧を読み取る入口として使う想定。"""
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
        logger.exception("evidence_aggregation_store: failed to get_recent_evidence_bundles")
        return []
