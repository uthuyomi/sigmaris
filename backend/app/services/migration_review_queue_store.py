# 役割: Phase E-4「マイグレーションレビュー待ちキュー」の永続化
# (sigmaris_migration_review_queue)。
#
# static_verification_store.py(Phase E-1)・sandbox_verification_
# store.py(Phase E-2)と同じservice_role_onlyパターンを踏襲した新規
# テーブル。
#
# 【重要】record_review_decision()は、人間が明示的に承認/却下を記録
# するための関数であり、どこからも自動的には呼ばれない——依頼書
# 「過度な自動化を避けること」への対応。このモジュール自身、また
# 呼び出し元のいずれにも、承認・却下を自動的に判定するロジックは
# 存在しない。

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.services.migration_review_queue import REVIEW_STATUSES, MigrationReviewEntry
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_migration_review_queue"


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


async def get_queued_hypothesis_ids() -> set[str]:
    """既にキューに存在する(レビュー状態を問わない)hypothesis_idの
    集合を返す。失敗時は空集合(fail-open)——判断根拠: この関数の
    唯一の呼び出し元(migration_review_queue_runner.py)は重複防止の
    ためだけにこれを使っており、取得に失敗しても「重複を許してでも
    キュー追加自体は続行する」方が、「キュー追加自体を止める」より
    安全側だと判断した(取りこぼしより重複の方が実害が小さい——
    人間が見て「あ、これはさっきも見た」と気づける)。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"select": "hypothesis_id", "limit": "1000"},
        )
        response.raise_for_status()
        data = response.json()
        return {row["hypothesis_id"] for row in data if isinstance(row, dict) and row.get("hypothesis_id")} if isinstance(data, list) else set()
    except Exception:
        logger.exception("migration_review_queue_store: failed to get_queued_hypothesis_ids")
        return set()


async def record_migration_review_entries(entries: list[MigrationReviewEntry]) -> list[str]:
    """新規のレビューエントリを、バルクINSERTで記録する。戻り値は
    新規行のidのリスト、失敗時は空リスト(例外は投げない、既存の全
    storeモジュールと同じベストエフォート方針)。entriesが0件の場合は
    HTTP通信すら発生させない。"""
    if not entries:
        return []
    try:
        payload = [
            {
                "hypothesis_id": e.hypothesis_id,
                "hypothesis_priority_id": e.hypothesis_priority_id,
                "static_verification_id": e.static_verification_id,
                "title": e.title,
                "what_is_problem": e.what_is_problem,
                "why_problem": e.why_problem,
                "how_to_improve": e.how_to_improve,
                "migration_reason": e.migration_reason,
                "source_evidence": e.source_evidence,
                "expected_metric_improvements": e.expected_metric_improvements,
                "d3_priority_rank": e.d3_priority_rank,
                "d3_priority_score": e.d3_priority_score,
                "review_status": e.review_status,
            }
            for e in entries
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
        logger.info("migration_review_queue_store: recorded %d entries", len(ids))
        return ids
    except Exception:
        logger.exception("migration_review_queue_store: failed to record migration review entries")
        return []


async def get_pending_reviews(*, limit: int = 50) -> list[dict[str, Any]]:
    """review_status="pending"の行を、新しい順に返す——人間がこれから
    判断すべき仮説の一覧。失敗時は空リスト。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"review_status": "eq.pending", "order": "created_at.desc", "limit": str(limit)},
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("migration_review_queue_store: failed to get_pending_reviews")
        return []


async def record_review_decision(
    queue_id: str, *, status: str, notes: str = "", reviewed_by: str = ""
) -> bool:
    """人間が下した承認/却下の判断を記録する。呼び出し元は常に人間
    (運用者が対話的に、またはこの関数を呼ぶ小さなスクリプト経由で
    明示的に)であり、どのRunner・スケジューラからも自動的には
    呼ばれない(依頼書「過度な自動化を避けること」への対応、この
    モジュールのdocstring参照)。

    statusは"approved"/"rejected"のみを受け付ける("pending"への
    差し戻しは、新規作成時のデフォルト以外では想定しない、意図的な
    制限)。不正な値の場合はValueErrorを送出する——依頼書が求める
    「明確なワークフロー」を、無効な状態遷移を許さないことで担保する。
    """
    if status not in ("approved", "rejected"):
        raise ValueError(f"status must be 'approved' or 'rejected', got: {status!r}")
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"id": f"eq.{queue_id}"},
            json={
                "review_status": status,
                "review_notes": notes,
                "reviewed_by": reviewed_by,
                "reviewed_at": datetime.now(UTC).isoformat(),
            },
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.exception("migration_review_queue_store: failed to record_review_decision for id=%s", queue_id)
        return False
