from __future__ import annotations

# X_POST_SELF_TIMING_SPEC の配信ディスパッチャ(フェーズC)の回帰テスト。
# ネットワーク/LLM 非依存: store・フィルタ・publisher・Gate をすべてモック
# して、_x_post_dispatch_check() の分岐(shadow ログのみ/opsec 再フィルタで
# skipped/live で post→posted)を検証する。

import asyncio
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services.proactive import scheduler as sched


def _run(coro):
    return asyncio.run(coro)


def _patches(*, due, privacy_ok=True, facts_ok=True, may_speak=True, live=False, tweet_id="tw1"):
    """_x_post_dispatch_check が使うインライン import 先をまとめてモックする。"""
    gate = AsyncMock(return_value=type("G", (), {"may_speak": may_speak, "blocked_by": None})())
    publisher = type("P", (), {"post_tweet": AsyncMock(return_value=tweet_id)})()
    return {
        "app.services.scheduled_x_post_store.get_due_pending": AsyncMock(return_value=due),
        "app.services.scheduled_x_post_store.mark_posted": AsyncMock(),
        "app.services.scheduled_x_post_store.mark_skipped": AsyncMock(),
        "app.services.x_post_generator.record_post": AsyncMock(),
        "app.services.x_privacy_filter.filter_private_info": (
            lambda text: (privacy_ok, [] if privacy_ok else ["IPアドレス"])
        ),
        "app.services.x_privacy_filter.filter_private_facts": AsyncMock(
            return_value=(facts_ok, [] if facts_ok else ["devices/x"])
        ),
        "app.services.executive_gate.evaluate_executive_gate": gate,
        "app.services.x_publisher.get_publisher": lambda: publisher,
        "_publisher": publisher,
    }


DUE = [{"id": "p1", "text": "おはよう", "category": "A_spontaneous_remark", "score": 1.0, "scheduled_at": "2026-07-23T09:00:00+00:00"}]


def _apply(mock_map, live):
    marks = {}
    ctxs = []
    for target, m in mock_map.items():
        if target.startswith("_"):
            continue
        p = patch(target, m)
        p.start()
        ctxs.append(p)
        marks[target] = m
    p_live = patch.object(settings, "x_categorized_post_live", live)
    p_live.start()
    ctxs.append(p_live)
    return ctxs, marks


def test_shadow_logs_only_and_marks_posted():
    m = _patches(due=DUE, live=False)
    ctxs, marks = _apply(m, live=False)
    try:
        with patch("app.services.proactive.scheduler.get_sigmaris_jwt", AsyncMock(return_value="jwt")):
            _run(sched._x_post_dispatch_check())
        # shadow: 実送信せず posted にする。
        marks["app.services.scheduled_x_post_store.mark_posted"].assert_awaited_once()
        m["_publisher"].post_tweet.assert_not_awaited()
        marks["app.services.scheduled_x_post_store.mark_skipped"].assert_not_awaited()
    finally:
        for c in ctxs:
            c.stop()


def test_opsec_block_marks_skipped():
    m = _patches(due=DUE, privacy_ok=False, live=False)
    ctxs, marks = _apply(m, live=False)
    try:
        with patch("app.services.proactive.scheduler.get_sigmaris_jwt", AsyncMock(return_value="jwt")):
            _run(sched._x_post_dispatch_check())
        marks["app.services.scheduled_x_post_store.mark_skipped"].assert_awaited_once()
        marks["app.services.scheduled_x_post_store.mark_posted"].assert_not_awaited()
    finally:
        for c in ctxs:
            c.stop()


def test_gate_block_marks_skipped():
    m = _patches(due=DUE, may_speak=False, live=False)
    ctxs, marks = _apply(m, live=False)
    try:
        with patch("app.services.proactive.scheduler.get_sigmaris_jwt", AsyncMock(return_value="jwt")):
            _run(sched._x_post_dispatch_check())
        marks["app.services.scheduled_x_post_store.mark_skipped"].assert_awaited_once()
        m["_publisher"].post_tweet.assert_not_awaited()
    finally:
        for c in ctxs:
            c.stop()


def test_live_posts_and_records():
    m = _patches(due=DUE, live=True, tweet_id="tw123")
    ctxs, marks = _apply(m, live=True)
    try:
        with patch("app.services.proactive.scheduler.get_sigmaris_jwt", AsyncMock(return_value="jwt")):
            _run(sched._x_post_dispatch_check())
        m["_publisher"].post_tweet.assert_awaited_once()
        marks["app.services.x_post_generator.record_post"].assert_awaited_once()
        marks["app.services.scheduled_x_post_store.mark_posted"].assert_awaited_once()
    finally:
        for c in ctxs:
            c.stop()


def test_no_due_does_nothing():
    m = _patches(due=[], live=False)
    ctxs, marks = _apply(m, live=False)
    try:
        with patch("app.services.proactive.scheduler.get_sigmaris_jwt", AsyncMock(return_value="jwt")):
            _run(sched._x_post_dispatch_check())
        marks["app.services.scheduled_x_post_store.mark_posted"].assert_not_awaited()
        marks["app.services.scheduled_x_post_store.mark_skipped"].assert_not_awaited()
    finally:
        for c in ctxs:
            c.stop()
