from __future__ import annotations

import unittest

from app.services.orchestrator.schedule_agent_client import _build_system_override


class ScheduleAgentClientTests(unittest.TestCase):
    def test_system_override_is_capped_for_agent_request_schema(self) -> None:
        override = _build_system_override(
            user_profile_context="profile:" + ("x" * 3000),
            self_model_context="self:" + ("y" * 1000),
            persona_context="persona:" + ("z" * 3000),
        )

        self.assertLessEqual(len(override), 4000)
        self.assertIn("You are Sigmaris.", override)
        self.assertIn("[context truncated]", override)


if __name__ == "__main__":
    unittest.main()
