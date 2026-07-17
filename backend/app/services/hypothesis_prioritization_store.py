# 役割: Phase D-3「優先順位付け・検証可能性の評価」の永続化
# (sigmaris_hypothesis_priorities)。
#
# hypothesis_store.py(Phase D-2)・evidence_aggregation_store.py
# (Phase D-1)と同じservice_role_onlyパターンを踏襲した新規テーブル。
#
# 【設計判断】D-2のsigmaris_hypotheses行を直接UPDATEするのではなく、
# 新規テーブルへ「1回の優先順位付け実行の結果」を追記する形にした——
# sigmaris_citation_audit_log/sigmaris_hypothesesが確立した「Sigmaris
# 自身の測定・評価データは追記専用ログとして扱う」という一貫した設計
# 判断を踏襲した。仮説そのもの(sigmaris_hypotheses)は不変の記録として
# 保ち、優先順位付けは「その時点のスナップショットに対する評価」として
# 独立させる——将来、同じ仮説群に対して条件を変えて再評価したくなった
# 場合(例: 検証可能指標の語彙を拡張した後の再ランキング)も、過去の
# 評価結果を上書きせずに済む。

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_hypothesis_priorities"


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


async def record_prioritization_run(
    *, run_at: str, normal_track: list[dict[str, Any]], special_review_track: list[dict[str, Any]]
) -> list[str]:
    """1回分の優先順位付け実行を、仮説1件=1行のバルクINSERTで記録する
    (hypothesis_store.record_hypotheses()と同じ「1件ずつの粒度で保存する」
    パターン)。戻り値は新規行のidのリスト、失敗時は空リスト(例外は
    投げない、既存の全storeモジュールと同じベストエフォート方針)。
    両トラックとも0件の場合はHTTP通信すら発生させない。"""
    rows = normal_track + special_review_track
    if not rows:
        return []
    try:
        payload = [
            {
                "run_at": run_at,
                "hypothesis_id": r.get("hypothesis_id"),
                "track": r.get("track"),
                "priority_rank": r.get("priority_rank"),
                "priority_score": r.get("priority_score"),
                "verifiability_checkable": r.get("verifiability", {}).get("checkable"),
                "verifiability_matched_metrics": r.get("verifiability", {}).get("matched_metrics") or [],
                "verifiability_reason": r.get("verifiability", {}).get("reason") or "",
                "phase_e_handoff": r.get("phase_e_handoff"),
            }
            for r in rows
        ]
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.post(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            json=payload,
        )
        response.raise_for_status()
        result = response.json()
        ids = [row.get("id") for row in result if isinstance(row, dict) and row.get("id")] if isinstance(result, list) else []
        logger.info("hypothesis_prioritization_store: recorded %d priority rows", len(ids))
        return ids
    except Exception:
        logger.exception("hypothesis_prioritization_store: failed to record prioritization run")
        return []


async def get_recent_prioritization_run(*, limit: int = 100) -> list[dict[str, Any]]:
    """直近の優先順位付け結果を新しい順に返す(Phase E側の将来の読み取り
    口を想定して用意)。失敗時は空リスト。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"order": "run_at.desc,priority_rank.asc.nullslast", "limit": str(limit)},
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("hypothesis_prioritization_store: failed to get_recent_prioritization_run")
        return []
