from __future__ import annotations

# 役割: アプリ内チャットデータの保存と取得を扱う。

from datetime import UTC, datetime
from typing import Any

from app.services.app_profile_data import get_profile_context
from app.services.supabase_rest import rest_delete, rest_insert, rest_select, rest_update


DEFAULT_THREAD_TITLE = "新しいチャット"
LEGACY_DEFAULT_THREAD_TITLE = "New chat"
THREAD_TITLE_MAX_LENGTH = 20


def compact_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted = []
    for part in parts:
        if part.get("type") == "file":
            next_part = dict(part)
            next_part["url"] = ""
            compacted.append(next_part)
        else:
            compacted.append(part)
    return compacted


def derive_thread_title(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        for part in message.get("parts", []):
            if part.get("type") == "text" and str(part.get("text", "")).strip():
                return str(part["text"]).strip()[:THREAD_TITLE_MAX_LENGTH]
        for part in message.get("parts", []):
            if part.get("type") == "file" and part.get("filename"):
                return str(part["filename"])[:THREAD_TITLE_MAX_LENGTH]
    return DEFAULT_THREAD_TITLE


async def get_chat_thread(jwt: str, thread_id: str) -> dict[str, Any] | None:
    return await rest_select(
        jwt,
        "chat_threads",
        {
            "select": "id,title,created_at,updated_at",
            "id": f"eq.{thread_id}",
        },
        single=True,
    )


async def replace_chat_messages(
    jwt: str,
    *,
    thread_id: str,
    messages: list[dict[str, Any]],
) -> None:
    context = await get_profile_context(jwt)
    user_id = context["userId"]

    await rest_delete(
        jwt,
        "chat_messages",
        {
            "user_id": f"eq.{user_id}",
            "thread_id": f"eq.{thread_id}",
        },
    )

    if messages:
        insert_payload = [
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "message_order": index,
                "role": message.get("role"),
                "parts": compact_parts(message.get("parts", [])),
                "metadata": message.get("metadata", {}),
            }
            for index, message in enumerate(messages)
        ]
        await rest_insert(jwt, "chat_messages", insert_payload)

    current_thread = await get_chat_thread(jwt, thread_id)
    if current_thread:
        current_title = current_thread.get("title")
        next_title = (
            derive_thread_title(messages)
            if current_title in {DEFAULT_THREAD_TITLE, LEGACY_DEFAULT_THREAD_TITLE}
            else current_title
        )
        await rest_update(
            jwt,
            "chat_threads",
            {
                "title": next_title,
                "updated_at": datetime.now(UTC).isoformat(),
            },
            {"id": f"eq.{thread_id}", "user_id": f"eq.{user_id}"},
        )
