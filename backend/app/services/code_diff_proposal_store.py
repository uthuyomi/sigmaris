# 役割: Phase F-1「仮説からコード差分への変換」の永続化
# (sigmaris_code_diff_proposals)。
#
# migration_review_queue_store.py(Phase E-4)と同じservice_role_only
# パターン・同じreview_statusワークフロー(pending/approved/rejected、
# 承認・却下は人間の明示的な呼び出しでのみ変わる)を踏襲した新規テーブル。
#
# 【絶対原則、このファイルにも実装しないこと】
# 本モジュールは、DBへの読み書き(Supabase REST経由)のみを行う。
# **git操作・ファイルシステムへの書き込みは一切行わない。** `subprocess`・
# `git`コマンド・GitHub API呼び出しは、このファイルのどこにも存在しない。
# record_review_decision()は、E-4のそれと全く同じ制約(approved/rejected
# のみを受け付け、pendingへの差し戻しを拒否)を持つ——ここでの
# "approved"は、あくまで「この差分提案を、人間が見て良いと判断した」
# という記録であり、それ自体がコミット・適用を引き起こすことは無い。
#
# 【Phase F-3追記(docs/sigmaris/phase_f_report.md)】
# 承認された差分を、実際にGitHub上のブランチ・コミット・PRへ変換する
# 仕組みが、diff_approval.py・github_pr_publisher.pyとして実装された。
# 本ファイルには、そのためのDB操作(get_diff_proposal_by_id・
# record_pr_outcome)のみを追加する——PR作成の実処理そのものは、
# 引き続き本ファイルの外(github_pr_publisher.py)にのみ存在する。

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_code_diff_proposals"


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


async def record_diff_proposals(proposals: list[dict[str, Any]]) -> list[str]:
    """生成済みの差分提案(安全性チェック通過・拒否のいずれも)を、
    バルクINSERTで記録する。戻り値は新規行のidのリスト、失敗時は空
    リスト(例外は投げない、既存の全storeモジュールと同じベスト
    エフォート方針)。proposalsが0件の場合はHTTP通信すら発生させない。
    """
    if not proposals:
        return []
    try:
        payload = [
            {
                "hypothesis_id": p.get("hypothesis_id"),
                "hypothesis_priority_id": p.get("hypothesis_priority_id"),
                "static_verification_id": p.get("static_verification_id"),
                "title": p.get("title"),
                "target_module": p.get("target_module"),
                "target_file": p.get("target_file"),
                "diff_text": p.get("diff_text") or "",
                "safety_check_status": p.get("safety_check_status"),
                "safety_check_reason": p.get("safety_check_reason") or "",
                # Phase F-2(docs/sigmaris/phase_f_report.md、hypothesis_
                # verification.py): この提案の元になった仮説が、E-1単独の
                # カバレッジ確認("hypothesis_verified_coverage")なのか、
                # E-2のサンドボックス基盤の可用性のみに基づく
                # ("sandbox_infra_available_unverified_content")なのかを
                # 記録する——後者は仮説の内容そのものを検証したものでは
                # 無いため、人間のレビュー時にこの区別が一目で分かる必要が
                # ある。
                "verification_tier": p.get("verification_tier"),
                "verification_tier_reason": p.get("verification_tier_reason") or "",
                "review_status": p.get("review_status", "pending"),
            }
            for p in proposals
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
        logger.info("code_diff_proposal_store: recorded %d proposals", len(ids))
        return ids
    except Exception:
        logger.exception("code_diff_proposal_store: failed to record diff proposals")
        return []


async def get_pending_diff_proposals(*, limit: int = 50) -> list[dict[str, Any]]:
    """review_status="pending"の行(=安全性チェックを通過し、人間の判断
    待ちの差分)を、新しい順に返す。失敗時は空リスト。"""
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
        logger.exception("code_diff_proposal_store: failed to get_pending_diff_proposals")
        return []


async def get_recent_diff_proposals(*, limit: int = 20) -> list[dict[str, Any]]:
    """Phase H-1(docs/sigmaris/phase_h_report.md): review_statusを問わず
    (pending/approved/rejected、pr_creation_status問わず)、直近の提案を
    新しい順に返す。X投稿カテゴリD・E(自己改善パイプラインの実況・技術
    記録)の材料収集用——「今日、パイプラインで何が起きたか」を一覧する
    ための、新規の読み取り専用アクセサ。get_pending_diff_proposals()と
    同じベストエフォート方針(失敗時は例外を投げず空リスト)。**新しい
    データ収集は行わない**——既存のsigmaris_code_diff_proposalsテーブル
    (F-1〜F-3が既に書き込み済み)を読むだけ。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"order": "created_at.desc", "limit": str(limit)},
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("code_diff_proposal_store: failed to get_recent_diff_proposals")
        return []


async def record_review_decision(
    proposal_id: str, *, status: str, notes: str = "", reviewed_by: str = ""
) -> bool:
    """人間が下した承認/却下の判断を記録するのみ。**この関数自体は、
    承認された差分をどこにも適用しない**——実際の適用(GitHub PR作成)は
    diff_approval.py::approve_diff_proposal()が、本関数の呼び出し後に
    別途、github_pr_publisher.pyへ委譲する。migration_review_queue_store.py::
    record_review_decision()と全く同じ制約(pendingへの差し戻しを拒否)。
    """
    if status not in ("approved", "rejected"):
        raise ValueError(f"status must be 'approved' or 'rejected', got: {status!r}")
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"id": f"eq.{proposal_id}"},
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
        logger.exception("code_diff_proposal_store: failed to record_review_decision for id=%s", proposal_id)
        return False


async def get_diff_proposal_by_id(proposal_id: str) -> dict[str, Any] | None:
    """Phase F-3: 承認・却下の判断、およびPR作成の実処理のために、1件の
    差分提案を、その全カラム(diff_text本文を含む)込みで取得する。
    見つからない、またはエラー時はNone(既存の全storeモジュールと
    同じベストエフォート方針——ただし呼び出し元のdiff_approval.pyは、
    Noneを「承認不可」として扱う、fail-closed)。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"id": f"eq.{proposal_id}", "limit": "1"},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data:
            return data[0]
        return None
    except Exception:
        logger.exception("code_diff_proposal_store: failed to get_diff_proposal_by_id for id=%s", proposal_id)
        return None


async def record_pr_outcome(
    proposal_id: str, *, status: str, pr_url: str = "", branch: str = "", error: str = ""
) -> bool:
    """Phase F-3: 承認後の実行結果(github_pr_publisher.pyの戻り値)を
    記録する。承認(record_review_decision)とは独立したカラムに記録する
    ——「人間が承認したかどうか」と「実際にPR作成まで到達したかどうか」を
    混同しないため(方針4「Constitutionチェックに後から抵触した場合は
    実行を中断し報告する」のケースでも、review_status="approved"のまま、
    pr_creation_status側だけが失敗を記録する、正直な監査証跡)。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"id": f"eq.{proposal_id}"},
            json={
                "pr_creation_status": status,
                "pr_url": pr_url,
                "pr_branch": branch,
                "pr_creation_error": error,
            },
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.exception("code_diff_proposal_store: failed to record_pr_outcome for id=%s", proposal_id)
        return False
