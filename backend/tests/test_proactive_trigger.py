from __future__ import annotations

# X_MANUAL_TRIGGER_SPEC の回帰テスト。
# ネットワーク非依存: proactive_trigger ハンドラを直接呼び、インライン import
# 先(scheduler の決定/配信関数・store・research)をモックして、各アクションが
# 対応関数をプロセス内で呼ぶこと・未知 action で 400・既存 research 不変を検証。

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routes.agent import ProactiveTriggerRequest, proactive_trigger

_AUTH = "Bearer dummy-jwt"


def _run(coro):
    return asyncio.run(coro)


def test_x_post_decision_calls_decider_and_returns_latest():
    decide = AsyncMock()
    recent = AsyncMock(return_value=[{"id": "p1", "scheduled_at": "2026-07-23T12:00:00+00:00"}])
    with patch("app.services.proactive.scheduler._categorized_x_post_check", decide), \
         patch("app.services.scheduled_x_post_store.get_recent_scheduled", recent):
        result = _run(proactive_trigger(ProactiveTriggerRequest(action="x_post_decision"), authorization=_AUTH))
    decide.assert_awaited_once()
    recent.assert_awaited_once()
    assert result["ok"] is True
    assert result["action"] == "x_post_decision"
    assert result["latest"][0]["id"] == "p1"


def test_x_post_dispatch_calls_dispatcher():
    dispatch = AsyncMock()
    with patch("app.services.proactive.scheduler._x_post_dispatch_check", dispatch):
        result = _run(proactive_trigger(ProactiveTriggerRequest(action="x_post_dispatch"), authorization=_AUTH))
    dispatch.assert_awaited_once()
    assert result == {"ok": True, "action": "x_post_dispatch"}


def test_research_still_works():
    run_research = AsyncMock(return_value={"found": 0})
    with patch("app.services.research_agent.run_research", run_research):
        result = _run(proactive_trigger(ProactiveTriggerRequest(action="research"), authorization=_AUTH))
    run_research.assert_awaited_once()
    assert result["ok"] is True
    assert result["action"] == "research"


def test_unknown_action_returns_400_with_all_valid():
    with pytest.raises(HTTPException) as exc:
        _run(proactive_trigger(ProactiveTriggerRequest(action="bogus"), authorization=_AUTH))
    assert exc.value.status_code == 400
    detail = exc.value.detail["error"]
    for action in ("research", "x_post_decision", "x_post_dispatch"):
        assert action in detail


def test_missing_auth_rejected():
    # 認証(_require_jwt)が維持されていること。
    with pytest.raises(HTTPException) as exc:
        _run(proactive_trigger(ProactiveTriggerRequest(action="x_post_dispatch"), authorization=None))
    assert exc.value.status_code == 401
