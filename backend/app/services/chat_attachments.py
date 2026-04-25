from __future__ import annotations

# 役割: チャット添付ファイルからモデル用の文脈を作る。

import base64
import json
from typing import Any

from app.services.import_extract import extract_schedule_from_image


def _parse_data_url(url: str) -> tuple[str, str] | None:
    if not url.startswith("data:") or "," not in url:
        return None
    header, payload = url.split(",", 1)
    media_type = header.removeprefix("data:").split(";", 1)[0] or "application/octet-stream"
    if ";base64" not in header:
        try:
            payload = base64.b64encode(payload.encode("utf-8")).decode("utf-8")
        except Exception:
            return None
    return media_type, payload


async def extract_latest_image_contexts(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_user_message = next(
        (message for message in reversed(messages) if message.get("role") == "user"),
        None,
    )
    if not latest_user_message:
        return []

    contexts: list[dict[str, Any]] = []
    for part in latest_user_message.get("parts", []):
        if part.get("type") != "file":
            continue
        media_type = str(part.get("mediaType", ""))
        if not media_type.startswith("image/"):
            continue
        parsed = _parse_data_url(str(part.get("url", "")))
        if not parsed:
            contexts.append(
                {
                    "filename": part.get("filename") or "image",
                    "error": "画像データを解析できませんでした。",
                }
            )
            continue
        parsed_media_type, base64_data = parsed
        try:
            preview = await extract_schedule_from_image(
                mime_type=parsed_media_type,
                base64_data=base64_data,
                filename=part.get("filename"),
            )
            contexts.append(
                {
                    "filename": part.get("filename") or "image",
                    "extracted": {
                        "summary": preview.summary,
                        "candidates": [
                            candidate.model_dump(by_alias=True) for candidate in preview.candidates
                        ],
                    },
                }
            )
        except Exception as error:  # noqa: BLE001
            contexts.append(
                {
                    "filename": part.get("filename") or "image",
                    "error": str(error),
                }
            )
    return contexts


def build_attachment_facts(image_contexts: list[dict[str, Any]]) -> str:
    if not image_contexts:
        return ""

    lines = [
        "最新のユーザーメッセージには画像添付が含まれている。",
        "以下は画像から抽出した予定候補の要約。画像が未着とは言わず、この情報を前提に会話すること。",
    ]
    for index, context in enumerate(image_contexts, start=1):
        if context.get("error"):
            lines.append(f"画像{index} ({context['filename']}): 解析失敗 - {context['error']}")
            continue
        extracted = context["extracted"]
        lines.append(
            "\n".join(
                [
                    f"画像{index} ({context['filename']})",
                    f"summary: {extracted['summary']}",
                    f"candidates: {json.dumps(extracted['candidates'], ensure_ascii=False)}",
                ]
            )
        )
    return "\n\n".join(lines)
