from __future__ import annotations

# 役割: Sigmaris Live「詳細表示、+機密情報のマスキング」タスク。
# live_detail_masking.pyでマスキング済みの詳細情報を、
# sigmaris_live_event_details(202608080066マイグレーション)へ
# 書き込み・読み出しする。
#
# 【fire-and-forgetパターン(Live-2〜4と同じ規律)】
# persist_live_event_detail_bg()は、emit_live_event()と同じく、呼び出し元
# からawaitせずに呼べる同期関数で、内部でasyncio.create_task()するのみ。
# ただしemit_live_event()と異なり、本処理はSupabase REST(Live-1、3.2節
# ベンチマークの対象外)への実際のHTTP書き込みを伴うため、待たずに
# 呼べることの意義が大きい——応答速度への影響を避けるため、失敗しても
# 例外を外へ伝播しない(内部try/exceptで自己完結する)、既存の
# _extract_facts_bg()等と同じ規律を踏襲する。
#
# 【なぜjwtをそのまま転送するか】
# rest_insert/rest_selectは、呼び出し元のJWTをそのままSupabase RESTへ
# 転送する(supabase_rest.py::_headers())。これにより、行レベル
# セキュリティ(auth.uid() = user_id)が、サービスロールを経由せず、
# 実際のユーザー本人の権限でのみ適用される——agent_invocation_audit_logs
# (audit.py)と全く同じ認可モデルをそのまま踏襲した。

import asyncio
import logging
from typing import Any

from app.services.supabase_rest import get_current_user, rest_insert, rest_select

logger = logging.getLogger(__name__)

TABLE = "sigmaris_live_event_details"


def persist_live_event_detail_bg(
    *,
    jwt: str,
    user_id: str,
    event_type: str,
    detail_key: str,
    masked_detail: dict[str, Any],
) -> None:
    """詳細情報の永続化を、fire-and-forgetで開始する。失敗しても、
    呼び出し元(記憶検索・ツール呼び出し本体の処理)には一切影響しない。
    呼び出し元が既にuser_idを持っている場合(orchestrator/service.py側)
    用——chat.py側はuser_idを持たないため、persist_live_event_detail_bg_
    from_jwt()を使う。"""
    asyncio.create_task(
        _persist_live_event_detail(
            jwt=jwt,
            user_id=user_id,
            event_type=event_type,
            detail_key=detail_key,
            masked_detail=masked_detail,
        ),
        name=f"live_event_detail:{event_type}:{detail_key}",
    )


def persist_live_event_detail_bg_from_jwt(
    *,
    jwt: str,
    event_type: str,
    detail_key: str,
    masked_detail: dict[str, Any],
) -> None:
    """persist_live_event_detail_bg()と同じだが、user_idをまだ持たない
    呼び出し元(chat.py::stream_chat_completion_ui()、HTTPホップ経由で
    呼ばれるため、orchestrator/service.pyと異なりuser_idを引き継いで
    いない——Live-2、11章1点目で既に文書化済みの、invocation_id/
    message_idの不一致と同種の制約)向け。get_current_user(jwt)による
    user_id解決も含め、fire-and-forgetタスク全体を1つにまとめることで、
    追加のSupabase Auth呼び出し(通常数十ms程度)が、応答ストリームを
    一切ブロックしないようにしている。"""
    asyncio.create_task(
        _persist_live_event_detail_from_jwt(
            jwt=jwt,
            event_type=event_type,
            detail_key=detail_key,
            masked_detail=masked_detail,
        ),
        name=f"live_event_detail:{event_type}:{detail_key}",
    )


async def _persist_live_event_detail_from_jwt(
    *,
    jwt: str,
    event_type: str,
    detail_key: str,
    masked_detail: dict[str, Any],
) -> None:
    try:
        user = await get_current_user(jwt)
        user_id = user.get("id") if isinstance(user, dict) else None
        if not user_id:
            logger.warning(
                "live_event_details: could not resolve user_id, skipping persist event_type=%s detail_key=%s",
                event_type,
                detail_key,
            )
            return
        await rest_insert(
            jwt,
            TABLE,
            {
                "user_id": user_id,
                "event_type": event_type,
                "detail_key": detail_key,
                "masked_detail": masked_detail,
            },
            single=True,
        )
    except Exception:
        logger.exception(
            "live_event_details: persist (from jwt) failed event_type=%s detail_key=%s",
            event_type,
            detail_key,
        )


async def _persist_live_event_detail(
    *,
    jwt: str,
    user_id: str,
    event_type: str,
    detail_key: str,
    masked_detail: dict[str, Any],
) -> None:
    try:
        await rest_insert(
            jwt,
            TABLE,
            {
                "user_id": user_id,
                "event_type": event_type,
                "detail_key": detail_key,
                "masked_detail": masked_detail,
            },
            single=True,
        )
    except Exception:
        logger.exception(
            "live_event_details: persist failed event_type=%s detail_key=%s",
            event_type,
            detail_key,
        )


async def get_live_event_detail(
    jwt: str, *, event_type: str, detail_key: str
) -> dict[str, Any] | None:
    """詳細情報を取得する。同じdetail_keyで複数行存在する場合(通常は
    発生しないはずだが、念のため)、最新の1件を返す。行が無い場合はNone
    (まだ書き込みが完了していない、または書き込みに失敗した場合を含む——
    fire-and-forgetのため、応答完了直後は取得できないことがある)。"""
    rows = await rest_select(
        jwt,
        TABLE,
        {
            "select": "masked_detail,created_at",
            "event_type": f"eq.{event_type}",
            "detail_key": f"eq.{detail_key}",
            "order": "created_at.desc",
            "limit": "1",
        },
    )
    if not isinstance(rows, list) or not rows:
        return None
    detail = rows[0].get("masked_detail")
    return detail if isinstance(detail, dict) else None
