# 役割: X_POST_SELF_TIMING_SPEC フェーズA(決定) — Sigmaris が投稿内容に
# 応じて「いつ出すか」を自分で決め、予約テーブルへ pending で積む。
#
# 【流れ】既存の generate_categorized_post() で {text, category, score} を
# 得たあと、時刻決定 LLM に現在JST日時・曜日・カテゴリ・本文を渡して「ふさ
# わしい未来の投稿時刻」を1つ返させる。返ってきた提案を、地平線内・深夜早朝
# 回避・最小間隔・1日上限のガードで検証し、外れたら丸める/棄却する。合格した
# ものだけを scheduled_x_posts へ status='pending' で積む(即送信はしない)。
#
# 【テスト非依存】時刻決定の LLM 呼び出しは decide_fn 引数で差し替え可能に
# して、ネットワーク非依存でガード(丸め/棄却)を検証できるようにしている。

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from app.config import settings

logger = logging.getLogger(__name__)

_JST = ZoneInfo("Asia/Tokyo")

# 深夜早朝(この時間帯には配信予約を置かない)。Executive Gate の quiet_hours
# と整合する保守的な範囲。ここに丸め込む場合は「同日か翌日の朝 _WAKE_HOUR」へ。
_QUIET_START_HOUR = 23  # 23:00〜
_QUIET_END_HOUR = 7     # 〜07:00(未満)
_WAKE_HOUR = 8          # 深夜早朝に当たった提案を丸める先(朝8時)


@dataclass(frozen=True)
class TimingDecision:
    scheduled_at: datetime  # JST aware。予約する未来時刻。
    reason: str


# 時刻決定 LLM を差し替えるための型。プロンプト(現在時刻・内容)を受け取り、
# ISO8601 の未来時刻文字列(JST)を返す。既定は _llm_decide_scheduled_at。
DecideFn = Callable[[str], Awaitable[str]]


def _is_quiet_hour(dt: datetime) -> bool:
    h = dt.astimezone(_JST).hour
    return h >= _QUIET_START_HOUR or h < _QUIET_END_HOUR


def _next_wake_time(dt: datetime) -> datetime:
    """深夜早朝に当たった dt を、直近の許容時刻(朝 _WAKE_HOUR)へ丸める。"""
    local = dt.astimezone(_JST)
    candidate = local.replace(hour=_WAKE_HOUR, minute=0, second=0, microsecond=0)
    if local.hour >= _QUIET_END_HOUR:
        # 夜側(23時台)→ 翌朝
        candidate = candidate + timedelta(days=1)
    # 早朝側(0〜7時未満)は当日の朝8時でよい
    return candidate


def _build_decision_prompt(*, category: str, text: str, now_jst: datetime) -> str:
    horizon_h = settings.x_post_schedule_horizon_h
    return "\n".join(
        [
            "You decide the best future time to post a tweet, based on its content.",
            f"Current time is {now_jst.isoformat(timespec='minutes')} (Asia/Tokyo, {now_jst.strftime('%A')}).",
            f"Category: {category}",
            f"Tweet text: {text}",
            "Pick ONE future posting time that fits the content's mood: morning greetings in the "
            "morning, reflections in the evening/night, technical notes during the day.",
            f"The time must be within the next {horizon_h} hours and must avoid late night / early "
            f"morning ({_QUIET_START_HOUR}:00-{_QUIET_END_HOUR}:00).",
            'Return JSON only: {"scheduled_at": "YYYY-MM-DDTHH:MM:SS+09:00", "reason": "..."}',
        ]
    )


async def _llm_decide_scheduled_at(prompt: str) -> str:
    from app.services.local_llm import TaskType, get_llm_router  # noqa: PLC0415

    router = get_llm_router()
    raw = await router.chat(
        TaskType.ROUTING,
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=200,
        json_mode=True,
    )
    payload = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict):
        raise ValueError("time-decider returned non-dict")
    return str(payload.get("scheduled_at") or "")


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_JST)
    return dt


def apply_timing_guards(
    proposed: datetime | None,
    *,
    now: datetime,
    existing_scheduled_ats: list[datetime],
) -> TimingDecision | None:
    """AI の提案時刻を検証し、丸めるか棄却する。合格なら TimingDecision、
    棄却なら None を返す。ガード:
      - 過去/直近すぎ → 棄却(未来のみ)
      - 地平線超過 → 棄却
      - 深夜早朝 → 直近の朝へ丸め
      - 既存予約と最小間隔未満 → 棄却
    """
    horizon = now + timedelta(hours=settings.x_post_schedule_horizon_h)
    min_gap = timedelta(minutes=settings.x_post_min_interval_min)

    if proposed is None:
        # 提案が不正(パース失敗)なら、安全な既定(2時間後、深夜なら朝へ丸め)。
        proposed = now + timedelta(hours=2)
        reason = "fallback(+2h): LLM proposal invalid"
    else:
        reason = "llm-proposed"

    # 未来であること(now より後)。過去/現在は数分先へ押し出さず棄却する
    # (決定機会は1日4回あり、無理に今すぐ出さない)。
    if proposed <= now:
        return None

    # 地平線超過は棄却。
    if proposed > horizon:
        return None

    # 深夜早朝は朝へ丸める。丸めた結果が地平線を超えたら棄却。
    if _is_quiet_hour(proposed):
        proposed = _next_wake_time(proposed)
        reason = f"{reason}+quiet-rounded"
        if proposed > horizon or proposed <= now:
            return None

    # 既存予約との最小間隔。近すぎるものが1つでもあれば棄却(連投防止)。
    for existing in existing_scheduled_ats:
        if abs((proposed - existing).total_seconds()) < min_gap.total_seconds():
            return None

    return TimingDecision(scheduled_at=proposed, reason=reason)


async def decide_scheduled_at(
    *,
    category: str,
    text: str,
    now: datetime,
    existing_scheduled_ats: list[datetime],
    decide_fn: DecideFn | None = None,
) -> TimingDecision | None:
    """内容から投稿時刻を1つ決めてガードにかける。合格なら TimingDecision。
    decide_fn を渡すとテストで LLM をダミー化できる。"""
    fn: DecideFn = decide_fn or _llm_decide_scheduled_at
    now_jst = now.astimezone(_JST)
    prompt = _build_decision_prompt(category=category, text=text, now_jst=now_jst)
    try:
        raw = await fn(prompt)
        proposed = _parse_iso(raw)
    except Exception:
        logger.exception("x_post_self_timing: time decision LLM failed")
        proposed = None
    return apply_timing_guards(proposed, now=now, existing_scheduled_ats=existing_scheduled_ats)
