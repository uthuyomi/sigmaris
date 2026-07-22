# 役割: X_POST_SELF_TIMING_SPEC の予約投稿(scheduled_x_posts)の永続化。
#
# x_post_history(H-1)・x_reply_log(H-2)・sigmaris_cycle_health_runs(Phase R)
# 等と同じ、service_role_only・単一テナントパターンを踏襲した新規テーブルの
# 読み書き(Supabase REST 経由)のみを行う。実際の投稿(post_tweet)・生成・
# フィルタ判定といった「行動の実行」は一切行わない——それらは決定フェーズ
# (x_post_self_timing.py)と配信ディスパッチャ(proactive/scheduler.py)の責務。

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "scheduled_x_posts"


def _svc_headers(*, representation: bool = False) -> dict[str, str]:
    _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if representation:
        headers["Prefer"] = "return=representation"
    return headers


def _today_start_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )


async def insert_scheduled_post(
    *, text: str, category: str, score: float, scheduled_at: datetime
) -> dict[str, Any] | None:
    """予約を1件、status='pending' で積む。作成した行(または None)を返す。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.post(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(representation=True),
            json={
                "text": text,
                "category": category,
                "score": score,
                "scheduled_at": scheduled_at.astimezone(timezone.utc).isoformat(),
                "status": "pending",
            },
        )
        if r.is_error:
            logger.warning("scheduled_x_post_store: insert failed status=%s", r.status_code)
            return None
        data = r.json()
        return data[0] if isinstance(data, list) and data else None
    except Exception:
        logger.exception("scheduled_x_post_store: insert_scheduled_post failed")
        return None


async def get_due_pending(*, now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    """status='pending' かつ scheduled_at<=now の予約を、古い順に取得する。
    未来分(scheduled_at>now)は返さない。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={
                "select": "id,text,category,score,scheduled_at,status",
                "status": "eq.pending",
                "scheduled_at": f"lte.{now.astimezone(timezone.utc).isoformat()}",
                "order": "scheduled_at.asc",
                "limit": str(limit),
            },
        )
        if r.is_error:
            return []
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("scheduled_x_post_store: get_due_pending failed")
        return []


async def count_today_scheduled_or_posted() -> int:
    """本日(UTC)の予約 scheduled_at を持つ pending+posted の合計件数。
    1日上限(MAX_DAILY_CATEGORY_POSTS)を予約数ベースで効かせるために使う
    (skipped は数えない——実際に出る/出す予定のものだけを上限対象にする)。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={
                "select": "id",
                "status": "in.(pending,posted)",
                "scheduled_at": f"gte.{_today_start_iso()}",
            },
        )
        if r.is_error:
            return 0
        data = r.json()
        return len(data) if isinstance(data, list) else 0
    except Exception:
        logger.exception("scheduled_x_post_store: count_today failed")
        return 0


async def get_pending_scheduled_ats() -> list[datetime]:
    """まだ配信していない(pending)予約の scheduled_at 一覧。最小間隔チェック用。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"select": "scheduled_at", "status": "eq.pending"},
        )
        if r.is_error:
            return []
        data = r.json()
        out: list[datetime] = []
        for row in data if isinstance(data, list) else []:
            raw = row.get("scheduled_at")
            if isinstance(raw, str):
                try:
                    out.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
                except ValueError:
                    continue
        return out
    except Exception:
        logger.exception("scheduled_x_post_store: get_pending_scheduled_ats failed")
        return []


async def mark_posted(post_id: str, *, tweet_id: str | None = None) -> None:
    await _update_status(post_id, status="posted", tweet_id=tweet_id, set_posted_at=True)


async def mark_skipped(post_id: str, *, reason: str) -> None:
    await _update_status(post_id, status="skipped", skip_reason=reason)


async def _update_status(
    post_id: str,
    *,
    status: str,
    skip_reason: str | None = None,
    tweet_id: str | None = None,
    set_posted_at: bool = False,
) -> None:
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        payload: dict[str, Any] = {"status": status}
        if skip_reason is not None:
            payload["skip_reason"] = skip_reason[:500]
        if tweet_id is not None:
            payload["tweet_id"] = tweet_id
        if set_posted_at:
            payload["posted_at"] = datetime.now(timezone.utc).isoformat()
        r = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"id": f"eq.{post_id}"},
            json=payload,
        )
        if r.is_error:
            logger.warning(
                "scheduled_x_post_store: status update failed id=%s status=%s http=%s",
                post_id, status, r.status_code,
            )
    except Exception:
        logger.exception("scheduled_x_post_store: _update_status failed id=%s", post_id)
