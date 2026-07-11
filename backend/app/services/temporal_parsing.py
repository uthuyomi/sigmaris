from __future__ import annotations

# 役割: シンプルなルールベースの日本語相対日付・絶対日付の抽出（Temporal Layer）。
#
# 意図的に大規模な自然言語時間解析ライブラリは使わない — Step 1
# (memory_extractor.py の valid_from 推定) で確立した制約「過度に複雑な
# 自然言語時間解析は行わないこと」を、Step 3 の日記的機能にもそのまま適用
# している。固定の関係フレーズ・正規表現による月日抽出のみで、複数の時間
# 表現が混在する文の厳密な解析等は行わない。

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Step 1 (memory_extractor.py の _estimate_valid_from) と Step 3
# (extract_diary_date_range 以下) の両方が使う、共通の相対日付フレーズ一覧。
# 元は memory_extractor.py 内に private な _RELATIVE_DATE_PHRASES として
# 定義されていたが、Step 3 で同じ変換テーブルを別の目的（日記的質問の日付
# レンジ抽出）に再利用する必要が生じたため、ここに切り出した
# （memory_extractor.py 側は本モジュールから re-export する形に変更した
# — 挙動は一切変えていない、純粋なリファクタリング）。
RELATIVE_DATE_PHRASES: list[tuple[str, int]] = [
    ("一昨日", -2),
    ("おととい", -2),
    ("昨日", -1),
    ("今日", 0),
    ("本日", 0),
    ("先週", -7),
    ("来週", 7),
    ("今週", 0),
    ("先月", -30),
    ("来月", 30),
    ("今月", 0),
]


def resolve_relative_date_phrase(text: str, *, now: datetime) -> datetime | None:
    """First-match offset lookup against RELATIVE_DATE_PHRASES. `now` is
    caller-supplied (not computed internally) so a caller can pass one
    consistent timestamp across several related calls, and so tests can
    freeze time deterministically."""
    for phrase, offset_days in RELATIVE_DATE_PHRASES:
        if phrase in text:
            return now + timedelta(days=offset_days)
    return None


# "7月3日" / "2026年7月3日" のような絶対日付表記のみを対象とする。
_ABSOLUTE_DATE_PATTERN = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日")

# 日記的質問であることを示す固定フレーズ集合（Temporal Layer Step 3）。
# 日付そのものへの言及だけでは発火させない — 「7月3日までに提出してくださ
# い」のような、日付が単なる期限として登場するだけのメッセージを日記的質問
# と誤認しないための精度ガード（依頼書の例「7月3日に何してた?」に忠実な、
# 意図的に狭いトリガー集合）。
_DIARY_TRIGGER_PHRASES = (
    "何してた",
    "何してました",
    "何をしてた",
    "何をしていた",
    "何があった",
    "どんな一日",
    "どんな日",
    "振り返って",
    "思い出して",
    "何をした",
)


def _resolve_absolute_date(text: str, *, now_jst: datetime) -> datetime | None:
    match = _ABSOLUTE_DATE_PATTERN.search(text)
    if not match:
        return None
    year_str, month_str, day_str = match.groups()
    month, day = int(month_str), int(day_str)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    year = int(year_str) if year_str else now_jst.year
    try:
        candidate = now_jst.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        return None  # e.g. 2月30日 -- not a real calendar date
    if not year_str and candidate > now_jst:
        # Year omitted and the resolved date is still in the future relative
        # to "now" (e.g. asked in January about "7月3日") -- assume last
        # year's occurrence rather than a future date, since a diary
        # question ("何してた") is inherently about the past.
        candidate = candidate.replace(year=year - 1)
    return candidate


def extract_diary_date_range(text: str, *, now: datetime) -> tuple[str, str] | None:
    """Detects a diary-style "what happened on <date>" question and returns
    a [date_from, date_to) UTC ISO range spanning that JST calendar day, or
    None when this message isn't a diary-style date question.

    Requires *both* a resolvable date reference (an absolute "7月3日"-style
    match, or one of RELATIVE_DATE_PHRASES) *and* one of
    _DIARY_TRIGGER_PHRASES. Absolute dates are tried first — a message
    containing both an absolute date and an incidental relative word should
    resolve to the explicit date, not the vaguer relative one.

    Known limitation (documented, not fixed here): 先週/今週/来週/先月/今月/
    来月 resolve to a single anchor day via RELATIVE_DATE_PHRASES (mirroring
    Step 1's existing single-point semantics exactly), not a full week/month
    range — this matches the task's explicit day-level example ("7月3日に
    何してた?") but under-serves a genuine "what happened this week"
    question, which would need a real range rather than one anchor day.
    """
    if not any(trigger in text for trigger in _DIARY_TRIGGER_PHRASES):
        return None

    tz = ZoneInfo("Asia/Tokyo")
    now_jst = now.astimezone(tz)

    resolved_jst = _resolve_absolute_date(text, now_jst=now_jst)
    if resolved_jst is None:
        resolved_jst = resolve_relative_date_phrase(text, now=now_jst)
    if resolved_jst is None:
        return None

    day_start = resolved_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return day_start.isoformat(), day_end.isoformat()
