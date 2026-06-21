from __future__ import annotations

import unittest

from app.services.orchestrator.response_guard import compare_mechanical_facts


class MechanicalResponseGuardTests(unittest.TestCase):
    def test_preserves_dates_numbers_urls_counts_and_success(self) -> None:
        source = (
            "2026-06-22 09:30の予定を2件登録しました。"
            "詳細は https://example.com/events/123 です。"
        )
        rewritten = (
            "やりましたね。2026-06-22 09:30の予定を2件登録しました。"
            "詳細は https://example.com/events/123 ですよ。"
        )

        result = compare_mechanical_facts(source, rewritten)

        self.assertTrue(result.passed)
        self.assertEqual(result.violations, ())

    def test_rejects_changed_number(self) -> None:
        source = "2026年6月22日 9:30に2件登録しました。"
        rewritten = "2026年6月22日 9:30に3件登録しました。"

        result = compare_mechanical_facts(source, rewritten)

        self.assertFalse(result.passed)
        self.assertIn("counts", result.violations)
        self.assertIn("numbers", result.violations)

    def test_rejects_success_changed_to_failure(self) -> None:
        result = compare_mechanical_facts(
            "予定の登録が完了しました。",
            "予定の登録に失敗しました。",
        )

        self.assertFalse(result.passed)
        self.assertIn("success/failure states", result.violations)

    def test_url_numbers_are_not_compared_as_standalone_numbers(self) -> None:
        result = compare_mechanical_facts(
            "詳細は https://example.com/events/123 です。",
            "詳細はこちらです: https://example.com/events/123",
        )

        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
