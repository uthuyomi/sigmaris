# 役割: Self-2「洗い出した機能の日本語への要約」(自己認識の自動更新、
# 第二段階、docs/sigmaris/self_awareness_report.md)— 生成された能力要約
# (`capability_summary.py`)の永続化(sigmaris_capability_summaries)。
#
# cycle_health_runs_store.py・evidence_aggregation_store.py・eval_runs_
# store.pyと全く同じ設計判断を踏襲した: service_role_onlyパターン、
# 書き込み失敗は例外を投げず記録するだけ(マイグレーション未適用の環境
# でも呼び出し元がクラッシュしないようにするため)。
#
# domain列がUNIQUEであるため、既存行の有無をSELECTで確認し、有れば
# PATCH・無ければPOSTする、self_model.py::update_self_model()と同じ
# 「既存 vs 新規」分岐パターンを採用した(判断根拠: 本テーブルは
# "最新の状態"のみを保持する設計であり、sigmaris_cycle_health_runs
# のような無制限追記の時系列テーブルではない——静的なコードのスキャン
# 結果に「時系列のトレンド」という意味は無いため、self_modelと同じ
# 「最新のみ保持」の設計をそのまま踏襲した、マイグレーションのコメント
# 参照)。

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_capability_summaries"


def _svc_headers(*, prefer_return: bool = True) -> dict[str, str]:
    _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer_return:
        headers["Prefer"] = "return=representation"
    return headers


async def get_capability_summaries() -> list[dict[str, Any]]:
    """全ドメインの最新要約を、domain順に返す。失敗時は空リスト
    (このコードベースの既存store関数と同じベストエフォート方針)。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer_return=False),
            params={"order": "domain.asc"},
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("capability_summary_store: failed to get_capability_summaries")
        return []


async def _get_by_domain(domain: str) -> dict[str, Any] | None:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    response = await client.get(
        f"{base_url}/rest/v1/{_TABLE}",
        headers=_svc_headers(prefer_return=False),
        params={"domain": f"eq.{domain}", "limit": "1"},
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list) and data:
        return data[0]
    return None


async def record_capability_summary(
    *,
    domain: str,
    summary_text: str,
    file_count: int,
    wired_file_count: int,
    unwired_file_count: int,
    source_files: list[str],
) -> str | None:
    """1ドメイン分の要約を記録する(既存行があれば上書き、無ければ新規
    作成)。戻り値は行のid、失敗時はNone(例外は投げない)。"""
    try:
        payload: dict[str, Any] = {
            "domain": domain,
            "summary_text": summary_text,
            "file_count": file_count,
            "wired_file_count": wired_file_count,
            "unwired_file_count": unwired_file_count,
            "source_files": source_files,
        }
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        existing = await _get_by_domain(domain)

        if existing is None:
            response = await client.post(
                f"{base_url}/rest/v1/{_TABLE}",
                headers=_svc_headers(),
                json=payload,
            )
        else:
            response = await client.patch(
                f"{base_url}/rest/v1/{_TABLE}",
                headers=_svc_headers(),
                params={"id": f"eq.{existing.get('id')}"},
                json=payload,
            )

        response.raise_for_status()
        rows = response.json()
        if isinstance(rows, list) and rows:
            row_id = rows[0].get("id")
            logger.info("capability_summary_store: recorded domain=%s id=%s", domain, row_id)
            return row_id
        return None
    except Exception:
        logger.exception("capability_summary_store: failed to record domain=%s", domain)
        return None
