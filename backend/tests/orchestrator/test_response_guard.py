from __future__ import annotations

import unittest

from app.services.orchestrator.response_guard import (
    compare_mechanical_facts,
    compare_response_to_tool_outputs,
)


class MechanicalResponseGuardTests(unittest.TestCase):
    def test_preserves_dates_numbers_urls_counts_and_success(self) -> None:
        source = (
            "Registered 2 events at 2026-06-22 09:30. "
            "Details: https://example.com/events/123"
        )
        rewritten = (
            "Done. Registered 2 events at 2026-06-22 09:30. "
            "Details: https://example.com/events/123"
        )

        result = compare_mechanical_facts(source, rewritten)

        self.assertTrue(result.passed)
        self.assertEqual(result.violations, ())

    def test_rejects_changed_number(self) -> None:
        result = compare_mechanical_facts(
            "Registered 2 events at 2026-06-22 09:30.",
            "Registered 3 events at 2026-06-22 09:30.",
        )

        self.assertFalse(result.passed)
        self.assertIn("numbers", result.violations)

    def test_rejects_success_changed_to_failure(self) -> None:
        result = compare_mechanical_facts(
            "The event was successfully registered.",
            "The event failed to register.",
        )

        self.assertFalse(result.passed)
        self.assertIn("success/failure states", result.violations)

    def test_url_numbers_are_not_compared_as_standalone_numbers(self) -> None:
        result = compare_mechanical_facts(
            "Details: https://example.com/events/123",
            "Details are here: https://example.com/events/123",
        )

        self.assertTrue(result.passed)

    def test_tool_output_guard_accepts_tool_grounded_time(self) -> None:
        result = compare_response_to_tool_outputs(
            tool_events=[
                {
                    "type": "tool-output-available",
                    "output": {"events": [{"title": "meeting", "start": "2026-07-07T10:00:00+09:00"}]},
                }
            ],
            response_text="meeting is at 2026-07-07 10:00.",
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.violations, ())

    def test_tool_output_guard_rejects_ungrounded_time(self) -> None:
        result = compare_response_to_tool_outputs(
            tool_events=[
                {
                    "type": "tool-output-available",
                    "output": {"events": [{"title": "meeting", "start": "2026-07-07T10:00:00+09:00"}]},
                }
            ],
            response_text="meeting is at 2026-07-07 15:00.",
        )

        self.assertFalse(result.passed)
        self.assertTrue(any("15:00" in violation for violation in result.violations))


if __name__ == "__main__":
    unittest.main()
