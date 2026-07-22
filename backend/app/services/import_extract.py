from __future__ import annotations

# 役割: 画像やシート行から予定候補を抽出する。
#
# IMPORT_EXTRACTION_REDESIGN: シフト表限定・硬いスキーマ・現在日付なしの
# 旧実装を、予定全般の画像/テキストへ汎用化しつつ、現在日付の接地・
# not-a-schedule ゲート・evidence(読み取り根拠)・インライン自己検証・
# Structured Outputs(スキーマ準拠保証)で誤爆を抑える。

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from app.config import settings
from app.schemas.import_preview import ImportPreview


def _today_grounding() -> str:
    tz = settings.sigmaris_timezone or "Asia/Tokyo"
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    return (
        f"Today is {today} ({tz}). "
        "Resolve relative dates (来週火曜, 明日, 今週末, 今度の金曜) and year-less "
        "dates (7/25, 7月25日) against this. Never guess a year without grounding."
    )


def _build_prompt() -> str:
    # 汎用抽出プロンプト。シフト表に限定せず、イベント告知・チラシ・チャット/
    # メールのスクショ・手書きメモ・ポスター等、予定/日時を含む画像やテキスト
    # 全般からイベントを抽出する。日本の日時慣習は維持。
    return "\n".join(
        [
            "You extract calendar events from images or spreadsheet rows.",
            "The source may be a shift table, an event flyer/poster, a chat or email "
            "screenshot, a handwritten memo, or any image/text that mentions plans "
            "with dates or times. Extract every event you can justify from the source.",
            _today_grounding(),
            # A-2 not-a-schedule ゲート
            "If the source contains no readable schedule or date/time information, "
            "return an empty candidates array and explain in summary that no schedule "
            "was detected. Never invent events that are not in the source.",
            # A-4 evidence + A-5 インライン自己検証
            "For each candidate, set evidence to a short verbatim quote of the source "
            "text/label you read it from (e.g. '7/25 早番 9:00-15:00'). Do not output "
            "any candidate whose evidence you cannot quote from the source.",
            "Only include candidates that are consistent with the source content. If a "
            "date or time is ambiguous, lower its confidence rather than guessing.",
            # スキーマ運用ルール(柔軟スキーマ)
            "date is required (YYYY-MM-DD). For a timed event set startTime (HH:mm) and, "
            "when known, endTime (HH:mm); leave endTime null if unknown. For an all-day "
            "event set allDay=true and leave startTime/endTime null.",
            "Set location when the source names a place; otherwise null.",
            "Give each candidate a title based on its content; use a generic name only "
            "when no better title can be read. Do not force the title '勤務'.",
            "Extract up to 100 candidates. Use Japan date and time conventions.",
        ]
    )


# Structured Outputs 用の JSON Schema(strict)。Responses API の
# text.format=json_schema に渡し、生成時点でスキーマ準拠を保証する。strict
# モードは全プロパティを required に列挙し additionalProperties=false を要求
# するため、任意フィールドは型に "null" を許容して None を表現する。
_PREVIEW_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "startTime": {"type": ["string", "null"], "description": "HH:mm or null"},
                    "endTime": {"type": ["string", "null"], "description": "HH:mm or null"},
                    "allDay": {"type": "boolean"},
                    "location": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "evidence": {"type": ["string", "null"]},
                    "confidence": {"type": ["number", "null"]},
                },
                "required": [
                    "title",
                    "date",
                    "startTime",
                    "endTime",
                    "allDay",
                    "location",
                    "description",
                    "evidence",
                    "confidence",
                ],
            },
        },
    },
    "required": ["summary", "candidates"],
}

_STRUCTURED_TEXT_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "schedule_import_preview",
        "strict": True,
        "schema": _PREVIEW_JSON_SCHEMA,
    }
}


def _get_openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set for backend.")
    return OpenAI(api_key=settings.openai_api_key)


def _model_name() -> str:
    return settings.openai_import_model or settings.openai_model


def _parse_preview_json(text: str) -> ImportPreview:
    # Structured Outputs でスキーマ準拠は保証されるが、Pydantic の
    # model_validator(all_day と時刻の整合など)は生成側では表現しきれない
    # ため、最終的な整合はここで担保する(不整合候補は ValueError で弾かれる)。
    payload = json.loads(text)
    return ImportPreview.model_validate(payload)


async def extract_schedule_from_sheet_rows(sheet_title: str, rows: list[list[str]]) -> ImportPreview:
    client = _get_openai_client()
    response = client.responses.create(
        model=_model_name(),
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": _build_prompt()}],
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
        text=_STRUCTURED_TEXT_FORMAT,
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
                "content": [{"type": "input_text", "text": _build_prompt()}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"Extract schedule candidates from this image{f' ({filename})' if filename else ''}.",
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{base64_data}",
                        "detail": "high",
                    },
                ],
            },
        ],
        text=_STRUCTURED_TEXT_FORMAT,
    )

    return _parse_preview_json(response.output_text)
