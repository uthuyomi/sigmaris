from __future__ import annotations

# 役割: チャットメッセージの整形と UI ストリーム変換を扱う。

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any


def _extract_text(parts: list[dict[str, Any]]) -> str:
    text_parts = [
        str(part.get("text", "")).strip()
        for part in parts
        if part.get("type") == "text" and str(part.get("text", "")).strip()
    ]
    return "\n".join(text_parts).strip()


def sanitize_messages_for_model(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for message in messages:
        text = _extract_text(message.get("parts", []))
        if not text:
            continue
        sanitized.append(
            {
                "role": message.get("role"),
                "content": text,
            }
        )
    return sanitized


def _to_response_content(role: str, text: str) -> list[dict[str, Any]]:
    if role == "assistant":
        return [{"type": "output_text", "text": text}]
    return [{"type": "input_text", "text": text}]



async def stream_ui_message_chunks(*, message_id: str, text: str) -> AsyncIterator[bytes]:
    text_part_id = str(uuid.uuid4())
    for chunk in (
        {"type": "start", "messageId": message_id},
        {"type": "text-start", "id": text_part_id},
    ):
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")

    slice_size = 48
    for index in range(0, len(text), slice_size):
        await asyncio.sleep(0)
        payload = {
            "type": "text-delta",
            "id": text_part_id,
            "delta": text[index:index + slice_size],
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    for chunk in (
        {"type": "text-end", "id": text_part_id},
        {"type": "finish", "finishReason": "stop"},
    ):
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
