# 役割: Phase D-2「仮説生成」の永続化(sigmaris_hypotheses)。
#
# evidence_aggregation_store.py(Phase D-1)・grounding_health_runs_store.py
# (Phase G-5)と同じservice_role_onlyパターンを踏襲した別テーブル。
#
# 【設計判断】sigmaris_evidence_bundles(D-1)は「1回の実行=1行、根拠は
# 全件まとめてitems jsonbに格納」という集約run形の設計だったが、
# sigmaris_hypothesesは意図的に「1件の仮説=1行」という粒度の細かい
# ログ形にした——理由は、sigmaris_citation_audit_log(Phase G-4、claim
# 単位の監査ログ)が既に確立した「個々の項目を後から独立に検索・集計
# したい場合は、run単位ではなく項目単位で行を分ける」という前例に従った
# ため。D-3(優先順位付け・検証可能性の評価、未実装)が、個々の仮説を
# 単独で参照・更新したくなる可能性が高いと判断した。

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_hypotheses"


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


async def record_hypotheses(
    evidence_bundle_id: str | None, hypotheses: list[dict[str, Any]]
) -> list[str]:
    """複数件の仮説を1回のバルクINSERTで記録する(citation_audit.py::
    persist_citation_audit()と同じ、1ターン分をまとめて書き込むパターン)。
    戻り値は新規行のidのリスト、失敗時は空リスト(例外は投げない、
    既存の全storeモジュールと同じベストエフォート方針)。空リストが
    渡された場合はHTTP通信すら発生させない。"""
    if not hypotheses:
        return []
    try:
        payload = [
            {
                "evidence_bundle_id": evidence_bundle_id,
                "source_evidence_category": h.get("source_evidence_category"),
                "source_evidence_title": h.get("source_evidence_title"),
                "evidence_priority_score": h.get("evidence_priority_score"),
                "title": h.get("title"),
                "what_is_problem": h.get("what_is_problem"),
                "why_problem": h.get("why_problem"),
                "how_to_improve": h.get("how_to_improve"),
                "expected_metric_improvements": h.get("expected_metric_improvements") or [],
                "requires_special_review": bool(h.get("requires_special_review")),
                "safety_review_reason": h.get("safety_review_reason") or "",
                "details": h.get("details") or {},
            }
            for h in hypotheses
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
        logger.info("hypothesis_store: recorded %d hypotheses", len(ids))
        return ids
    except Exception:
        logger.exception("hypothesis_store: failed to record hypotheses")
        return []


async def get_recent_hypotheses(*, limit: int = 20, requires_special_review: bool | None = None) -> list[dict[str, Any]]:
    """直近の仮説を新しい順に返す。requires_special_reviewを指定すると
    その値で絞り込む(D-3が「要確認の仮説だけをレビューする」ような
    運用をしたくなった場合の入口として用意した)。失敗時は空リスト。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        params: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
        if requires_special_review is not None:
            params["requires_special_review"] = f"eq.{str(requires_special_review).lower()}"
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("hypothesis_store: failed to get_recent_hypotheses")
        return []
