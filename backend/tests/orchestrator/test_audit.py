from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.orchestrator.audit import finish_invocation, start_invocation


class InvocationAuditTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.services.orchestrator.audit.rest_insert", new_callable=AsyncMock)
    async def test_start_requires_persisted_row(self, rest_insert: AsyncMock) -> None:
        rest_insert.return_value = {}

        with self.assertRaisesRegex(RuntimeError, "persisted row"):
            await start_invocation(
                jwt="jwt",
                invocation_id="11111111-1111-1111-1111-111111111111",
                user_id="22222222-2222-2222-2222-222222222222",
                caller_agent_id="sigmaris-orchestrator",
                target_agent_id="schedule-agent",
                target_endpoint="/api/agent/chat/complete",
                reason="test",
                request_summary={},
                persona_version="v1",
                persona_hash="hash",
            )

    @patch("app.services.orchestrator.audit.rest_update", new_callable=AsyncMock)
    async def test_finish_requires_exactly_one_updated_row(
        self, rest_update: AsyncMock
    ) -> None:
        rest_update.return_value = []

        with self.assertRaisesRegex(RuntimeError, "not persisted"):
            await finish_invocation(
                jwt="jwt",
                audit_row_id="33333333-3333-3333-3333-333333333333",
                status="completed",
                response_summary={},
                error_code=None,
                duration_ms=10,
            )


if __name__ == "__main__":
    unittest.main()
