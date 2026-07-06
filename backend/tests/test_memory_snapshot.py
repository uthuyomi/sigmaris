from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.memory_snapshot import build_memory_snapshot_payload
from app.services.orchestrator import service as orchestrator_service


class MemorySnapshotTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.services.memory_snapshot.get_entities_and_relations", new_callable=AsyncMock)
    @patch("app.services.memory_snapshot.get_active_goal_alignment_flags", new_callable=AsyncMock)
    @patch("app.services.memory_snapshot.get_current_and_previous_topic", new_callable=AsyncMock)
    @patch("app.services.memory_snapshot.get_active_preference_patterns", new_callable=AsyncMock)
    async def test_build_memory_snapshot_payload_aggregates_existing_outputs(
        self,
        get_active_preference_patterns: AsyncMock,
        get_current_and_previous_topic: AsyncMock,
        get_active_goal_alignment_flags: AsyncMock,
        get_entities_and_relations: AsyncMock,
    ) -> None:
        get_active_preference_patterns.return_value = [{"pattern_key": "speed"}]
        get_current_and_previous_topic.return_value = (
            {"id": "topic-current", "topic_label": "current"},
            {"id": "topic-prev", "topic_label": "previous"},
        )
        get_active_goal_alignment_flags.return_value = [{"id": "flag-1"}]
        get_entities_and_relations.return_value = (
            [{"id": "entity-1", "name": "Project"}],
            [{"from_entity_id": "entity-1", "to_entity_id": "entity-2"}],
        )

        payload = await build_memory_snapshot_payload("user-id")

        self.assertEqual(payload["user_id"], "user-id")
        self.assertEqual(payload["preference_patterns"], [{"pattern_key": "speed"}])
        self.assertEqual(payload["topic_state"]["current"]["id"], "topic-current")
        self.assertEqual(payload["topic_state"]["previous"]["id"], "topic-prev")
        self.assertEqual(payload["goal_alignment_flags"], [{"id": "flag-1"}])
        self.assertEqual(payload["entities"], [{"id": "entity-1", "name": "Project"}])
        self.assertEqual(payload["relations"], [{"from_entity_id": "entity-1", "to_entity_id": "entity-2"}])

    def test_snapshot_context_parts_filters_recently_surfaced_goal_flags(self) -> None:
        orchestrator_service._recently_surfaced_goal_flag_ids.clear()
        orchestrator_service._recently_surfaced_goal_flag_ids.add("flag-1")

        parts = orchestrator_service._snapshot_context_parts(
            {
                "preference_patterns": [{"pattern_key": "speed"}],
                "topic_state": {
                    "current": {"id": "topic-current", "topic_label": "current"},
                    "previous": {"id": "topic-prev", "topic_label": "previous"},
                },
                "goal_alignment_flags": [{"id": "flag-1"}, {"id": "flag-2"}],
                "entities": [{"id": "entity-1"}],
                "relations": [{"from_entity_id": "entity-1"}],
            }
        )

        preference_patterns, current_topic, previous_topic, goal_flags, entities, relations = parts
        self.assertEqual(preference_patterns, [{"pattern_key": "speed"}])
        self.assertEqual(current_topic["id"], "topic-current")
        self.assertEqual(previous_topic["id"], "topic-prev")
        self.assertEqual(goal_flags, [{"id": "flag-2"}])
        self.assertEqual(entities, [{"id": "entity-1"}])
        self.assertEqual(relations, [{"from_entity_id": "entity-1"}])

        orchestrator_service._recently_surfaced_goal_flag_ids.clear()


if __name__ == "__main__":
    unittest.main()
