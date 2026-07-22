from __future__ import annotations

# IMPORT_EXTRACTION_REDESIGN の回帰テスト。
# ネットワーク非依存: vision/OpenAI 呼び出しはせず、期待 JSON フィクスチャで
# スキーマ・validator・日付接地プロンプトを検証する。

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.config import settings
from app.schemas.import_preview import ImportCandidate, ImportPreview


# ─── スキーマ / validator ────────────────────────────────────────────
def test_timed_candidate_ok():
    c = ImportCandidate.model_validate(
        {"title": "早番", "date": "2026-07-25", "startTime": "09:00", "endTime": "15:00",
         "evidence": "7/25 早番 9:00-15:00", "confidence": 0.9}
    )
    assert c.all_day is False
    assert c.start_time == "09:00"
    assert c.location is None


def test_all_day_candidate_ok():
    c = ImportCandidate.model_validate(
        {"title": "祝日", "date": "2026-07-25", "allDay": True, "evidence": "海の日"}
    )
    assert c.all_day is True
    assert c.start_time is None and c.end_time is None


def test_candidate_with_location():
    c = ImportCandidate.model_validate(
        {"title": "ライブ", "date": "2026-08-01", "startTime": "18:00",
         "location": "Zepp Sapporo", "evidence": "8/1 18:00 Zepp Sapporo"}
    )
    assert c.location == "Zepp Sapporo"


def test_end_time_optional():
    c = ImportCandidate.model_validate(
        {"title": "打合せ", "date": "2026-07-25", "startTime": "10:00"}
    )
    assert c.end_time is None


def test_timed_without_start_rejected():
    with pytest.raises(ValidationError):
        ImportCandidate.model_validate({"title": "x", "date": "2026-07-25"})


def test_all_day_with_time_rejected():
    with pytest.raises(ValidationError):
        ImportCandidate.model_validate(
            {"title": "x", "date": "2026-07-25", "allDay": True, "startTime": "09:00"}
        )


def test_confidence_range_enforced():
    with pytest.raises(ValidationError):
        ImportCandidate.model_validate(
            {"title": "x", "date": "2026-07-25", "startTime": "09:00", "confidence": 1.5}
        )


# ─── フィクスチャ(期待 JSON がスキーマを通ること) ─────────────────────
def test_fixture_shift_table_multiple_timed():
    preview = ImportPreview.model_validate(
        {
            "summary": "3件の勤務を検出",
            "candidates": [
                {"title": "早番", "date": "2026-07-25", "startTime": "09:00", "endTime": "15:00",
                 "evidence": "7/25 早番 9-15", "confidence": 0.9},
                {"title": "遅番", "date": "2026-07-26", "startTime": "15:00", "endTime": "22:00",
                 "evidence": "7/26 遅番 15-22", "confidence": 0.9},
                {"title": "休", "date": "2026-07-27", "allDay": True,
                 "evidence": "7/27 休", "confidence": 0.8},
            ],
        }
    )
    assert len(preview.candidates) == 3
    assert preview.candidates[2].all_day is True


def test_fixture_flyer_single_with_location():
    preview = ImportPreview.model_validate(
        {
            "summary": "イベント告知を1件検出",
            "candidates": [
                {"title": "夏祭り", "date": "2026-08-15", "startTime": "17:00", "endTime": "21:00",
                 "location": "中央公園", "evidence": "8/15 17:00-21:00 中央公園", "confidence": 0.85},
            ],
        }
    )
    assert preview.candidates[0].location == "中央公園"


def test_fixture_not_a_schedule_is_empty():
    preview = ImportPreview.model_validate(
        {"summary": "予定を検出できませんでした。", "candidates": []}
    )
    assert preview.candidates == []


# ─── A-1 現在日付・タイムゾーンの接地 ────────────────────────────────
def test_prompt_contains_today_and_timezone():
    from app.services.import_extract import _build_prompt, _today_grounding

    prompt = _build_prompt()
    tz = settings.sigmaris_timezone or "Asia/Tokyo"
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    assert today in prompt, "prompt must ground on today's date"
    assert tz in prompt, "prompt must mention the timezone"
    # 相対/年なし日付の解決指示があること
    assert "relative dates" in _today_grounding()
    assert re.search(r"\d{4}-\d{2}-\d{2}", prompt)


def test_prompt_has_evidence_and_not_a_schedule_rules():
    from app.services.import_extract import _build_prompt

    prompt = _build_prompt()
    assert "evidence" in prompt
    assert "empty candidates array" in prompt  # not-a-schedule ゲート
    assert "allDay" in prompt  # 終日スキーマ運用
