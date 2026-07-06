from __future__ import annotations

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.orchestrator.schedule_agent_client import (
    ScheduleAgentResult,
    ScheduleAgentStreamEvent,
)
from app.services.orchestrator.service import run_orchestrator_chat, run_orchestrator_chat_stream


def _close_background_coro(coro, *, name: str | None = None):  # noqa: ARG001
    if hasattr(coro, "close"):
        coro.close()
    return SimpleNamespace(cancel=lambda: None)


class OrchestratorServiceTests(unittest.IsolatedAsyncioTestCase):
    def _patch_common(self, stack: ExitStack) -> dict[str, object]:
        persona = SimpleNamespace(version="v1", sha256="hash", content="persona document")
        mocks: dict[str, object] = {}
        mocks["load_persona"] = stack.enter_context(
            patch("app.services.orchestrator.service.load_persona", return_value=persona)
        )
        mocks["get_current_user"] = stack.enter_context(
            patch(
                "app.services.orchestrator.service.get_current_user",
                new=AsyncMock(return_value={"id": "user-id", "user_metadata": {"name": "Kai"}}),
            )
        )
        mocks["start_invocation"] = stack.enter_context(
            patch(
                "app.services.orchestrator.service.start_invocation",
                new=AsyncMock(return_value={"id": "audit-row-id"}),
            )
        )
        mocks["finish_invocation"] = stack.enter_context(
            patch("app.services.orchestrator.service.finish_invocation", new=AsyncMock())
        )
        stack.enter_context(
            patch(
                "app.services.orchestrator.service._cached_user_profile",
                new=AsyncMock(return_value={"call_name": "Kai"}),
            )
        )
        stack.enter_context(
            patch("app.services.orchestrator.service._cached_self_model", new=AsyncMock(return_value=None))
        )
        stack.enter_context(
            patch(
                "app.services.orchestrator.service._cached_threshold_adjustment",
                new=AsyncMock(return_value=0.0),
            )
        )
        stack.enter_context(
            patch("app.services.orchestrator.service._cached_active_trends", new=AsyncMock(return_value=[]))
        )
        stack.enter_context(
            patch(
                "app.services.orchestrator.service._prepare_session_messages",
                new=AsyncMock(return_value=("thread-id", [{"role": "user", "content": "hello"}], False)),
            )
        )
        stack.enter_context(
            patch("app.services.orchestrator.service._cached_fact_items", new=AsyncMock(return_value=[]))
        )
        stack.enter_context(
            patch(
                "app.services.orchestrator.service._cached_memory_snapshot",
                new=AsyncMock(
                    return_value={
                        "preference_patterns": [],
                        "topic_state": {"current": None, "previous": None},
                        "goal_alignment_flags": [],
                        "entities": [],
                        "relations": [],
                    }
                ),
            )
        )
        stack.enter_context(
            patch("app.services.orchestrator.service._build_memory_context", new=AsyncMock(return_value="memory"))
        )
        stack.enter_context(patch("app.services.orchestrator.service.asyncio.create_task", _close_background_coro))
        mocks["take_pending_inquiry_question"] = stack.enter_context(
            patch(
                "app.services.active_inquiry.take_pending_inquiry_question",
                return_value=None,
            )
        )
        return mocks

    async def test_audit_start_failure_prevents_agent_call(self) -> None:
        with ExitStack() as stack:
            self._patch_common(stack)
            stack.enter_context(
                patch(
                    "app.services.orchestrator.service.start_invocation",
                    new=AsyncMock(side_effect=RuntimeError("audit unavailable")),
                )
            )
            call_schedule_agent = stack.enter_context(
                patch("app.services.orchestrator.service.call_schedule_agent", new=AsyncMock())
            )

            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                await run_orchestrator_chat(
                    jwt="jwt",
                    google_access_token=None,
                    google_refresh_token=None,
                    messages=[{"role": "user", "content": "hello"}],
                    thread_id=None,
                    request_context=None,
                )

            call_schedule_agent.assert_not_awaited()

    async def test_unified_generation_passes_persona_context_without_rewrite(self) -> None:
        with ExitStack() as stack:
            self._patch_common(stack)
            call_schedule_agent = stack.enter_context(
                patch("app.services.orchestrator.service.call_schedule_agent", new=AsyncMock())
            )
            call_schedule_agent.return_value = ScheduleAgentResult(
                text="Hello from ShiftPilot.",
                thread_id="thread-id",
                message_id="message-id",
            )

            result = await run_orchestrator_chat(
                jwt="jwt",
                google_access_token=None,
                google_refresh_token=None,
                messages=[{"role": "user", "content": "hello"}],
                thread_id=None,
                request_context=None,
            )

            self.assertTrue(result["ok"])
            self.assertNotIn("ShiftPilot", result["text"])
            kwargs = call_schedule_agent.await_args.kwargs
            self.assertIn("Sigmaris unified-generation context", kwargs["persona_context"])
            self.assertIn("PERSONA_VERSION", kwargs["persona_context"])

    async def test_pending_inquiry_is_not_surfaced_by_default(self) -> None:
        with ExitStack() as stack:
            mocks = self._patch_common(stack)
            take_pending = mocks["take_pending_inquiry_question"]
            take_pending.return_value = "ちなみに、GPUはGTX 1660のままで合っていますか？"
            call_schedule_agent = stack.enter_context(
                patch("app.services.orchestrator.service.call_schedule_agent", new=AsyncMock())
            )
            call_schedule_agent.return_value = ScheduleAgentResult(
                text="2日ぶりだね、海星さん。",
                thread_id="thread-id",
                message_id="message-id",
            )

            result = await run_orchestrator_chat(
                jwt="jwt",
                google_access_token=None,
                google_refresh_token=None,
                messages=[{"role": "user", "content": "いやぁ2日ぶり"}],
                thread_id=None,
                request_context=None,
            )

            self.assertEqual(result["text"], "2日ぶりだね、海星さん。")
            take_pending.assert_not_called()

    async def test_completion_audit_failure_fails_whole_invocation(self) -> None:
        with ExitStack() as stack:
            mocks = self._patch_common(stack)
            finish_invocation = mocks["finish_invocation"]
            assert isinstance(finish_invocation, AsyncMock)
            finish_invocation.side_effect = RuntimeError("audit update unavailable")
            call_schedule_agent = stack.enter_context(
                patch("app.services.orchestrator.service.call_schedule_agent", new=AsyncMock())
            )
            call_schedule_agent.return_value = ScheduleAgentResult(
                text="No events.",
                thread_id="thread-id",
                message_id="message-id",
            )

            with self.assertRaisesRegex(RuntimeError, "audit update unavailable"):
                await run_orchestrator_chat(
                    jwt="jwt",
                    google_access_token=None,
                    google_refresh_token=None,
                    messages=[{"role": "user", "content": "hello"}],
                    thread_id=None,
                    request_context=None,
                )

    async def test_stream_relays_tool_event_and_preserves_confirmation_marker(self) -> None:
        marker_text = (
            "Ready to register.\n"
            '<!-- shiftpilot-confirmation {"tool":"create_app_events","arguments":{"title":"demo"}} -->'
        )
        tool_event = {
            "type": "tool-output-available",
            "toolCallId": "call-1",
            "output": {"ok": True},
            "dynamic": True,
        }

        async def fake_stream(**kwargs):  # noqa: ANN003
            self.assertIn("Sigmaris unified-generation context", kwargs["persona_context"])
            yield ScheduleAgentStreamEvent(tool_event=tool_event)
            yield ScheduleAgentStreamEvent(delta=marker_text)
            yield ScheduleAgentStreamEvent(done=True, thread_id="thread-id", message_id="message-id")

        with ExitStack() as stack:
            self._patch_common(stack)
            stack.enter_context(patch("app.services.orchestrator.service.call_schedule_agent_stream", fake_stream))

            events = [
                event
                async for event in run_orchestrator_chat_stream(
                    jwt="jwt",
                    google_access_token=None,
                    google_refresh_token=None,
                    messages=[{"role": "user", "content": "please add this"}],
                    thread_id=None,
                    request_context=None,
                )
            ]

        self.assertEqual(events[0].tool_event, tool_event)
        self.assertIn("shiftpilot-confirmation", "".join(event.delta for event in events))
        self.assertTrue(events[-1].done)


if __name__ == "__main__":
    unittest.main()
