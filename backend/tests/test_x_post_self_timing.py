from __future__ import annotations

# X_POST_SELF_TIMING_SPEC の回帰テスト(フェーズA 決定 + ガード)。
# ネットワーク/LLM 非依存: 時刻決定 LLM は decide_fn へダミー注入し、ガード
# (地平線/深夜回避/最小間隔/未来のみ)の丸め・棄却を検証する。

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.x_post_self_timing import (
    apply_timing_guards,
    decide_scheduled_at,
)

_JST = ZoneInfo("Asia/Tokyo")


def _jst(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=_JST)


# 基準時刻: 2026-07-23(木) 14:00 JST(日中)。
NOW = _jst(2026, 7, 23, 14, 0)


# ─── ガード: 未来のみ ────────────────────────────────────────────────
def test_past_proposal_rejected():
    past = NOW - timedelta(hours=1)
    assert apply_timing_guards(past, now=NOW, existing_scheduled_ats=[]) is None


def test_now_or_earlier_rejected():
    assert apply_timing_guards(NOW, now=NOW, existing_scheduled_ats=[]) is None


# ─── ガード: 地平線 ──────────────────────────────────────────────────
def test_within_horizon_accepted():
    proposed = NOW + timedelta(hours=5)  # 19:00、日中、地平線内
    d = apply_timing_guards(proposed, now=NOW, existing_scheduled_ats=[])
    assert d is not None
    assert d.scheduled_at == proposed


def test_beyond_horizon_rejected():
    beyond = NOW + timedelta(hours=settings.x_post_schedule_horizon_h + 2)
    assert apply_timing_guards(beyond, now=NOW, existing_scheduled_ats=[]) is None


# ─── ガード: 深夜早朝の丸め ──────────────────────────────────────────
def test_late_night_rounded_to_morning():
    # 23:30 JST の提案(深夜)→ 翌朝8:00 へ丸め。地平線(24h)内に収まる。
    late = _jst(2026, 7, 23, 23, 30)
    d = apply_timing_guards(late, now=NOW, existing_scheduled_ats=[])
    assert d is not None
    local = d.scheduled_at.astimezone(_JST)
    assert local.hour == 8 and local.day == 24


def test_early_morning_rounded_same_day():
    # now を深夜寄りにして、早朝5:00 の提案 → 当日朝8:00 へ丸め。
    now = _jst(2026, 7, 23, 3, 0)
    early = _jst(2026, 7, 23, 5, 0)
    d = apply_timing_guards(early, now=now, existing_scheduled_ats=[])
    assert d is not None
    local = d.scheduled_at.astimezone(_JST)
    assert local.hour == 8 and local.day == 23


# ─── ガード: 最小間隔 ────────────────────────────────────────────────
def test_too_close_to_existing_rejected():
    proposed = NOW + timedelta(hours=5)          # 19:00
    close = proposed + timedelta(minutes=30)     # 既存予約が30分違い
    # min_interval は既定90分なので棄却されるはず。
    assert apply_timing_guards(proposed, now=NOW, existing_scheduled_ats=[close]) is None


def test_far_enough_from_existing_accepted():
    proposed = NOW + timedelta(hours=5)                    # 19:00
    far = NOW + timedelta(hours=5) + timedelta(minutes=settings.x_post_min_interval_min + 10)
    d = apply_timing_guards(proposed, now=NOW, existing_scheduled_ats=[far])
    assert d is not None


# ─── ガード: 不正提案(None)→ 安全な既定へフォールバック ─────────────
def test_invalid_proposal_falls_back_to_default():
    d = apply_timing_guards(None, now=NOW, existing_scheduled_ats=[])
    assert d is not None  # +2h(=16:00、日中)へフォールバック
    assert d.scheduled_at == NOW + timedelta(hours=2)
    assert "fallback" in d.reason


# ─── decide_scheduled_at: ダミー LLM 注入 ────────────────────────────
def test_decide_with_dummy_llm_valid():
    async def dummy(prompt: str) -> str:
        return (NOW + timedelta(hours=6)).isoformat()  # 20:00、日中

    d = asyncio.run(
        decide_scheduled_at(
            category="A_spontaneous_remark", text="おはよう", now=NOW,
            existing_scheduled_ats=[], decide_fn=dummy,
        )
    )
    assert d is not None
    assert d.scheduled_at == NOW + timedelta(hours=6)


def test_decide_with_dummy_llm_garbage_falls_back():
    async def dummy(prompt: str) -> str:
        return "not-a-timestamp"

    d = asyncio.run(
        decide_scheduled_at(
            category="A_spontaneous_remark", text="テスト", now=NOW,
            existing_scheduled_ats=[], decide_fn=dummy,
        )
    )
    # パース失敗 → フォールバック(+2h)で救済される。
    assert d is not None
    assert d.scheduled_at == NOW + timedelta(hours=2)


def test_decide_with_dummy_llm_beyond_horizon_rejected():
    async def dummy(prompt: str) -> str:
        return (NOW + timedelta(hours=100)).isoformat()

    d = asyncio.run(
        decide_scheduled_at(
            category="E_technical_record", text="技術ネタ", now=NOW,
            existing_scheduled_ats=[], decide_fn=dummy,
        )
    )
    assert d is None  # 地平線超過は棄却
