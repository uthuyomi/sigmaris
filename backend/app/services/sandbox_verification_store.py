# 役割: Phase E-2「別ポートでの動的検証」の永続化
# (sigmaris_sandbox_verifications)。
#
# static_verification_store.py(Phase E-1)と同じservice_role_only
# パターンを踏襲した新規テーブル。
#
# 【設計判断】1回のサンドボックス起動セッション=1行、とした(E-1の
# 「仮説1件=1行」とは異なる粒度)。判断根拠: このサンドボックス検証は、
# 仮説の内容を一切読まない、環境レベルの健全性確認(起動できたか・
# 軽量ヘルスチェックがエラーを出さなかったか)であり、複数の仮説に
# またがる「今回のセッションの基盤自体は健全だった」という、単一の
# 結果を表す。個々の仮説との対応は、candidate_hypothesis_ids(jsonb
# 配列)として、参考情報の形で1行の中に保持する。

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_sandbox_verifications"


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


async def record_sandbox_verification(
    *,
    run_at: str,
    port: int,
    started: bool,
    startup_detail: str,
    verdict: str,
    health_checks: list[dict[str, Any]],
    candidate_hypothesis_ids: list[str],
    terminated_cleanly: bool,
) -> str | None:
    """1回分のサンドボックス検証セッションを記録する。戻り値は新規行の
    id、失敗時はNone(例外は投げない、既存の全storeモジュールと同じ
    ベストエフォート方針)。"""
    try:
        payload: dict[str, Any] = {
            "run_at": run_at,
            "port": port,
            "started": started,
            "startup_detail": startup_detail,
            "verdict": verdict,
            "health_checks": health_checks,
            "candidate_hypothesis_ids": candidate_hypothesis_ids,
            "terminated_cleanly": terminated_cleanly,
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
            logger.info("sandbox_verification_store: recorded run id=%s", row_id)
            return row_id
        return None
    except Exception:
        logger.exception("sandbox_verification_store: failed to record sandbox verification")
        return None


async def get_recent_sandbox_verifications(*, limit: int = 20) -> list[dict[str, Any]]:
    """直近のサンドボックス検証結果を新しい順に返す。失敗時は空リスト。"""
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
        logger.exception("sandbox_verification_store: failed to get_recent_sandbox_verifications")
        return []
