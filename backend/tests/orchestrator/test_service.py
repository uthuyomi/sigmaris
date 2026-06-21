from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.orchestrator.persona_rewriter import PersonaRewriteResult
from app.services.orchestrator.schedule_agent_client import ScheduleAgentResult
from app.services.orchestrator.service import run_orchestrator_chat


class OrchestratorServiceAuditTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.services.orchestrator.service.call_schedule_agent", new_callable=AsyncMock)
    @patch("app.services.orchestrator.service.start_invocation", new_callable=AsyncMock)
    @patch("app.services.orchestrator.service.load_persona")
    @patch("app.services.orchestrator.service.get_current_user", new_callable=AsyncMock)
    async def test_audit_start_failure_prevents_agent_call(
        self,
        get_current_user: AsyncMock,
        load_persona,
        start_invocation: AsyncMock,
        call_schedule_agent: AsyncMock,
    ) -> None:
        get_current_user.return_value = {"id": "user-id", "user_metadata": {}}
        load_persona.return_value = type(
            "Persona",
            (),
            {"version": "v1", "sha256": "hash", "content": "persona"},
        )()
        start_invocation.side_effect = RuntimeError("audit unavailable")

        with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
            await run_orchestrator_chat(
                jwt="jwt",
                google_access_token=None,
                google_refresh_token=None,
                messages=[{"role": "user", "content": "明日の予定"}],
                thread_id=None,
                request_context=None,
            )

        call_schedule_agent.assert_not_awaited()

    @patch("app.services.orchestrator.service.finish_invocation", new_callable=AsyncMock)
    @patch("app.services.orchestrator.service.rewrite_with_persona", new_callable=AsyncMock)
    @patch("app.services.orchestrator.service.call_schedule_agent", new_callable=AsyncMock)
    @patch("app.services.orchestrator.service.start_invocation", new_callable=AsyncMock)
    @patch("app.services.orchestrator.service.load_persona")
    @patch("app.services.orchestrator.service.get_current_user", new_callable=AsyncMock)
    async def test_completion_audit_failure_fails_whole_invocation(
        self,
        get_current_user: AsyncMock,
        load_persona,
        start_invocation: AsyncMock,
        call_schedule_agent: AsyncMock,
        rewrite_with_persona: AsyncMock,
        finish_invocation: AsyncMock,
    ) -> None:
        get_current_user.return_value = {"id": "user-id", "user_metadata": {}}
        load_persona.return_value = type(
            "Persona",
            (),
            {"version": "v1", "sha256": "hash", "content": "persona"},
        )()
        start_invocation.return_value = {"id": "audit-row-id"}
        call_schedule_agent.return_value = ScheduleAgentResult(
            text="予定はありません。",
            thread_id="thread-id",
            message_id="message-id",
        )
        rewrite_with_persona.return_value = PersonaRewriteResult(
            text="予定はありませんよ。",
            used_fallback=False,
            guard_violations=(),
        )
        finish_invocation.side_effect = RuntimeError("audit update unavailable")

        with self.assertRaisesRegex(RuntimeError, "audit update unavailable"):
            await run_orchestrator_chat(
                jwt="jwt",
                google_access_token=None,
                google_refresh_token=None,
                messages=[{"role": "user", "content": "明日の予定"}],
                thread_id=None,
                request_context=None,
            )


if __name__ == "__main__":
    unittest.main()
