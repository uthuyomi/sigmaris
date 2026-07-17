# 役割: Phase H-2「返信の検知、及び、フィルタリング」の永続化
# (x_reply_log)。
#
# x_post_history(H-1)・sigmaris_cycle_health_runs(Phase R)等と同じ、
# service_role_only・単一テナントパターンを踏襲した新規テーブル。
#
# 【絶対原則、このファイルにも実装しないこと】
# 本モジュールは、DBへの読み書き(Supabase REST経由)のみを行う。実際の
# 返信文の生成・投稿・その他いかなる「行動の実行」も、一切行わない
# (依頼書「本タスクの範囲は、検知とフィルタリングまでとする」への
# 直接対応)。record_detected_reply()が記録するfilter_outcomeは、あくまで
# 「対話の対象として扱ってよいと判定したかどうか」の記録であり、それ
# 自体が何かを実行することはない。

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "x_reply_log"


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


async def get_processed_reply_ids(reply_tweet_ids: list[str]) -> set[str]:
    """渡されたtweet_idのうち、既に処理済み(x_reply_logに記録済み)の
    ものだけを返す。重複検知の防止に使う——失敗時は空集合を返す
    (fail-open ではなく、呼び出し元が「念のため処理をスキップする」
    方向に倒せるよう、空集合=「何も処理済みでない」という保守的でない
    結果になる点に注意——判断根拠はx_reply_detector.py参照)。"""
    if not reply_tweet_ids:
        return set()
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        ids_param = ",".join(reply_tweet_ids)
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"select": "reply_tweet_id", "reply_tweet_id": f"in.({ids_param})"},
        )
        response.raise_for_status()
        data = response.json()
        return {row["reply_tweet_id"] for row in data if isinstance(row, dict) and row.get("reply_tweet_id")}
    except Exception:
        logger.exception("x_reply_log_store: failed to get_processed_reply_ids")
        return set()


async def record_detected_reply(
    *,
    reply_tweet_id: str,
    in_reply_to_tweet_id: str,
    author_id: str | None,
    author_username: str | None,
    reply_text: str,
    filter_outcome: str,
    filter_reasons: list[str],
) -> str | None:
    """検知した返信1件の、検知・フィルタリング結果を記録する。戻り値は
    新規行のid、失敗時はNone(例外は投げない、既存の全storeモジュールと
    同じベストエフォート方針)。"""
    if filter_outcome not in ("developer_bypass", "eligible", "ignored"):
        raise ValueError(f"filter_outcome must be one of developer_bypass/eligible/ignored, got: {filter_outcome!r}")
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.post(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            json={
                "reply_tweet_id": reply_tweet_id,
                "in_reply_to_tweet_id": in_reply_to_tweet_id,
                "author_id": author_id,
                "author_username": author_username,
                "reply_text": reply_text,
                "filter_outcome": filter_outcome,
                "filter_reasons": filter_reasons,
            },
        )
        response.raise_for_status()
        rows = response.json()
        if isinstance(rows, list) and rows:
            return rows[0].get("id")
        return None
    except Exception:
        logger.exception("x_reply_log_store: failed to record_detected_reply reply_tweet_id=%s", reply_tweet_id)
        return None


async def get_recent_eligible_replies(*, limit: int = 50) -> list[dict[str, Any]]:
    """filter_outcomeが"eligible"(開発者以外・フィルタ通過)または
    "developer_bypass"(開発者本人)の、直近の返信を新しい順に返す。
    次のタスク(返信文の生成)が参照する、唯一の読み取り口として用意した
    ——本タスク自体は、これを使って何かを実行することはない。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={
                "select": "*",
                "filter_outcome": "in.(eligible,developer_bypass)",
                "order": "detected_at.desc",
                "limit": str(limit),
            },
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("x_reply_log_store: failed to get_recent_eligible_replies")
        return []
