from __future__ import annotations

# 役割: 画像やシート行から予定候補を抽出する。

import json

from openai import OpenAI

from app.config import settings
from app.schemas.import_preview import ImportPreview

PROMPT_BASE = "\n".join(
    [
        "You extract work schedule candidates from images or spreadsheet rows.",
        "Return JSON only.",
        "Use this exact schema: {\"summary\": string, \"candidates\": [{\"title\": string, \"date\": \"YYYY-MM-DD\", \"startTime\": \"HH:mm\", \"endTime\": \"HH:mm\", \"description\": string|null, \"confidence\": number|null}]}",
        "If information is ambiguous, keep only entries you can justify from the source.",
        "Extract every schedule candidate present in the provided rows, up to 100 candidates. Do not stop after 10 items when more justified entries are present.",
        "Use the generic title '勤務' when no better title is available.",
        "Use Japan date and time conventions.",
    ]
)


def _get_openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set for backend.")
    return OpenAI(api_key=settings.openai_api_key)


def _model_name() -> str:
    return settings.openai_import_model or settings.openai_model


def _parse_preview_json(text: str) -> ImportPreview:
    payload = json.loads(text)
    return ImportPreview.model_validate(payload)


async def extract_schedule_from_sheet_rows(sheet_title: str, rows: list[list[str]]) -> ImportPreview:
    client = _get_openai_client()
    response = client.responses.create(
        model=_model_name(),
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": PROMPT_BASE}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "\n\n".join(
                            [
                                f"Sheet title: {sheet_title}",
                                "Extract schedule candidates from the following rows.",
                                json.dumps(rows, ensure_ascii=False),
                            ]
                        ),
                    }
                ],
            },
        ],
    )

    return _parse_preview_json(response.output_text)


async def extract_schedule_from_image(
    *, mime_type: str, base64_data: str, filename: str | None = None
) -> ImportPreview:
    client = _get_openai_client()
    response = client.responses.create(
        model=_model_name(),
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": PROMPT_BASE}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"Extract schedule candidates from this image{f' ({filename})' if filename else ''}. Return JSON only.",
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{base64_data}",
                        "detail": "high",
                    },
                ],
            },
        ],
    )

    return _parse_preview_json(response.output_text)
