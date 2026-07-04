from __future__ import annotations

# Phase B9: knowledge graph layer (final Phase B feature).
#
# Deliberately mirrors goal_alignment.py's (Phase B16) pipeline shape
# rather than inventing a sixth variant — B16's own report flagged that
# B2/B6/B14/B15/B16 had each independently built the same "weekly extract
# -> global service-role table -> TTL-cached injection" pipeline, and this
# task's instructions explicitly forbid adding a sixth independent
# implementation. Consolidating the five existing ones is out of scope
# here (a future refactor task) — this module just follows the same shape
# rather than deviating from it.
#
# Minimum-viable schema (task's overriding constraint): two plain
# PostgreSQL tables (sigmaris_entities, sigmaris_entity_relations),
# traversable with ordinary SQL joins — no graph database, no query
# language, no traversal engine. See the migration file's own comment for
# why this never duplicates user_fact_items/sigmaris_decision_log/
# sigmaris_topic_log/sigmaris_user_preference_patterns' actual content —
# relations only ever point back at those rows (source_table/source_id),
# never copy them.
#
# Weekly fire-and-forget extraction (Sunday 5:15 — see proactive/
# scheduler.py — the 30-minute gap between narrative_generate at 5:00 and
# self_interest_queries at 5:30), reading from exactly the same three
# sources goal_alignment.py (B16) already reads (category='goals' facts,
# recent decisions, recent topics) rather than adding a fourth new read
# path.
#
# B7 integration (multihop_search.py) adds zero new LLM calls: entities/
# relations already extracted here are matched against the user's query by
# plain substring containment (no LLM), and surfaced as an optional hint
# string appended to decompose_query()'s existing prompt — the exact same
# "optional hint block" mechanism B7 already uses for recent topic labels
# (_format_topic_hint), just with a second hint source.

import json
import logging
from typing import Any

from app.config import settings
from app.services.decision_log import get_recent_decisions
from app.services.local_llm import TaskType, get_llm_router
from app.services.supabase_rest import _get_client, _require_supabase_config
from app.services.topic_tracker import get_recent_topics
from app.services.user_fact_data import get_fact_items_for_user

logger = logging.getLogger(__name__)

_ENTITIES_TABLE = "sigmaris_entities"
_RELATIONS_TABLE = "sigmaris_entity_relations"

_VALID_ENTITY_TYPES = frozenset({"person", "place", "project", "technology", "other"})

# Same volume gate philosophy as B14/B16 — nothing meaningful to extract
# relationships from below this many decisions.
_MIN_DECISIONS_FOR_ANALYSIS = 3

_RECENT_DECISIONS_LIMIT = 50
_RECENT_TOPICS_LIMIT = 20

# How many entities/relations _cached fetch (orchestrator/service.py)
# pulls per turn for hint-matching — the graph is expected to stay small
# (weekly-extracted, not per-message), so this is a generous ceiling, not
# a tuned production limit.
_HINT_LOOKUP_LIMIT = 200

_EXTRACT_SYSTEM = (
    "あなたはシグマリスのナレッジグラフ抽出システムです。海星さんに関する記"
    "録から、人物・場所・プロジェクト・技術要素などのエンティティと、それら"
    "の間の関係性を抽出します。既存の記録の内容を複製するのではなく、エンテ"
    "ィティ名と関係の種類のみを短く抽出してください。必ず有効なJSONのみを返"
    "してください。"
)

_EXTRACT_PROMPT = """海星さんの長期的な目標(user_fact_itemsのcategory=goals):
{goals}

## 直近の決定記録({decision_count}件、sigmaris_decision_log)
{decisions}

## 直近の話題の推移({topic_count}件、sigmaris_topic_log)
{topics}

---
上記から、人物・場所・プロジェクト・技術要素などのエンティティと、それらの間の
明確な関係性を抽出してください。

**重要な制約:**
- エンティティ名と種別、関係の種類のみを短く記述すること。決定の詳細な理由や内
  容そのものを複製しないこと(それらは既存の記録にそのまま残っている)
- 明確に読み取れる関係のみを抽出し、推測で関係をでっち上げないこと
- source_refには、根拠とした決定または話題のid(上記に付与されているものをそ
  のまま)を1つ指定すること

以下のJSON形式で出力してください:
{{
  "relations": [
    {{
      "from_entity": {{"name": "エンティティ名", "type": "person/place/project/technology/otherのいずれか"}},
      "to_entity": {{"name": "エンティティ名", "type": "person/place/project/technology/otherのいずれか"}},
      "relation_type": "関係を表す短い語句(例: 取り組んでいる、の一部である、に関連する)",
      "source_ref": "根拠のid"
    }}
  ]
}}
何も見つからなければ {{"relations": []}} を返してください。"""


def _svc_headers(*, prefer: str | None = None) -> dict[str, str]:
    _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    h: dict[str, str] = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


async def _get_or_create_entity(name: str, entity_type: str) -> str | None:
    """Idempotent get-or-create, matched on (name, entity_type) — the
    table's own unique constraint. No evidence accumulation needed here
    (unlike B14/B16's pattern rows): an entity either exists or doesn't,
    there's no "how many times has this been confirmed" concept for a
    bare name+type."""
    base_url, _ = _require_supabase_config()
    client = await _get_client()

    existing_resp = await client.get(
        f"{base_url}/rest/v1/{_ENTITIES_TABLE}",
        headers=_svc_headers(),
        params={"name": f"eq.{name}", "entity_type": f"eq.{entity_type}", "select": "id"},
    )
    existing_resp.raise_for_status()
    existing_rows = existing_resp.json()
    if isinstance(existing_rows, list) and existing_rows:
        return existing_rows[0].get("id")

    create_resp = await client.post(
        f"{base_url}/rest/v1/{_ENTITIES_TABLE}",
        headers=_svc_headers(prefer="return=representation"),
        json={"name": name, "entity_type": entity_type},
    )
    create_resp.raise_for_status()
    rows = create_resp.json()
    return rows[0].get("id") if isinstance(rows, list) and rows else None


async def _get_or_create_relation(
    *,
    from_entity_id: str,
    to_entity_id: str,
    relation_type: str,
    source_table: str | None,
    source_id: str | None,
) -> str | None:
    base_url, _ = _require_supabase_config()
    client = await _get_client()

    existing_resp = await client.get(
        f"{base_url}/rest/v1/{_RELATIONS_TABLE}",
        headers=_svc_headers(),
        params={
            "from_entity_id": f"eq.{from_entity_id}",
            "to_entity_id": f"eq.{to_entity_id}",
            "relation_type": f"eq.{relation_type}",
            "select": "id",
        },
    )
    existing_resp.raise_for_status()
    existing_rows = existing_resp.json()
    if isinstance(existing_rows, list) and existing_rows:
        return existing_rows[0].get("id")

    payload: dict[str, Any] = {
        "from_entity_id": from_entity_id,
        "to_entity_id": to_entity_id,
        "relation_type": relation_type,
    }
    if source_table is not None:
        payload["source_table"] = source_table
    if source_id is not None:
        payload["source_id"] = source_id

    create_resp = await client.post(
        f"{base_url}/rest/v1/{_RELATIONS_TABLE}",
        headers=_svc_headers(prefer="return=representation"),
        json=payload,
    )
    create_resp.raise_for_status()
    rows = create_resp.json()
    return rows[0].get("id") if isinstance(rows, list) and rows else None


async def extract_entities_and_relations(user_id: str) -> dict[str, Any]:
    """Sunday 5:15 AM scheduled: extract entities/relations from the same
    three sources goal_alignment.py (B16) already reads. Fire-and-forget,
    zero response-path impact.
    """
    result: dict[str, Any] = {
        "goals_found": 0,
        "decisions_analyzed": 0,
        "topics_analyzed": 0,
        "relations_found": 0,
        "relations_stored": 0,
        "errors": 0,
        "insufficient_data": False,
    }
    try:
        goals = await get_fact_items_for_user(user_id, category="goals", active_only=True)
        result["goals_found"] = len(goals)

        decisions = await get_recent_decisions(limit=_RECENT_DECISIONS_LIMIT)
        result["decisions_analyzed"] = len(decisions)

        topics = await get_recent_topics(limit=_RECENT_TOPICS_LIMIT)
        result["topics_analyzed"] = len(topics)

        if len(decisions) < _MIN_DECISIONS_FOR_ANALYSIS:
            result["insufficient_data"] = True
            logger.info(
                "knowledge_graph: extraction skipped — decisions=%d (need >= %d)",
                len(decisions), _MIN_DECISIONS_FOR_ANALYSIS,
            )
            return result

        valid_refs = {d.get("id") for d in decisions if d.get("id")} | {
            t.get("id") for t in topics if t.get("id")
        }

        goal_lines = "\n".join(f"- key={g.get('key')} value={g.get('value')}" for g in goals) or "（なし）"
        decision_lines = "\n".join(
            f"- id={d.get('id')} title={d.get('title')} reason={(d.get('reason') or 'N/A')[:150]}"
            for d in decisions
        ) or "（なし）"
        topic_lines = "\n".join(
            f"- id={t.get('id')} label={t.get('topic_label')}" for t in topics
        ) or "（なし）"

        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": _EXTRACT_PROMPT.format(
                    goals=goal_lines,
                    decision_count=len(decisions),
                    decisions=decision_lines,
                    topic_count=len(topics),
                    topics=topic_lines,
                )},
            ],
            temperature=0.2,
            max_tokens=800,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        candidates = parsed.get("relations") if isinstance(parsed, dict) else None
        if not isinstance(candidates, list):
            candidates = []
        result["relations_found"] = len(candidates)

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            from_entity = candidate.get("from_entity")
            to_entity = candidate.get("to_entity")
            relation_type = str(candidate.get("relation_type") or "").strip()
            if not isinstance(from_entity, dict) or not isinstance(to_entity, dict) or not relation_type:
                continue

            from_name = str(from_entity.get("name") or "").strip()
            from_type = str(from_entity.get("type") or "").strip()
            to_name = str(to_entity.get("name") or "").strip()
            to_type = str(to_entity.get("type") or "").strip()
            if not from_name or not to_name:
                continue
            if from_type not in _VALID_ENTITY_TYPES or to_type not in _VALID_ENTITY_TYPES:
                continue

            # Only trust a source_ref that actually exists among the
            # decisions/topics we sent — never take an LLM-invented id at
            # face value (same defensive pattern as B7/B14/B16).
            source_ref = candidate.get("source_ref")
            source_id = source_ref if isinstance(source_ref, str) and source_ref in valid_refs else None
            source_table = None
            if source_id is not None:
                source_table = (
                    "sigmaris_decision_log"
                    if source_id in {d.get("id") for d in decisions}
                    else "sigmaris_topic_log"
                )

            try:
                from_id = await _get_or_create_entity(from_name, from_type)
                to_id = await _get_or_create_entity(to_name, to_type)
                if not from_id or not to_id:
                    continue
                await _get_or_create_relation(
                    from_entity_id=from_id,
                    to_entity_id=to_id,
                    relation_type=relation_type,
                    source_table=source_table,
                    source_id=source_id,
                )
                result["relations_stored"] += 1
            except Exception:
                logger.exception(
                    "knowledge_graph: failed to store relation %s -[%s]-> %s",
                    from_name, relation_type, to_name,
                )
                result["errors"] += 1

        logger.info(
            "knowledge_graph: extraction done decisions=%d topics=%d found=%d stored=%d",
            result["decisions_analyzed"], result["topics_analyzed"],
            result["relations_found"], result["relations_stored"],
        )
        return result
    except Exception:
        logger.exception("knowledge_graph: failed to extract_entities_and_relations")
        result["errors"] += 1
        return result


async def get_entities_and_relations(
    limit: int = _HINT_LOOKUP_LIMIT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch a bounded snapshot of the graph for hint-matching (Phase B9's
    B7 integration). Intended to be called through an orchestrator-level
    TTL cache (mirroring every other B-group context source), not once per
    turn directly."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()

        entities_resp = await client.get(
            f"{base_url}/rest/v1/{_ENTITIES_TABLE}",
            headers=_svc_headers(),
            params={"select": "id,name,entity_type", "limit": str(limit)},
        )
        entities_resp.raise_for_status()
        entities = entities_resp.json()
        entities = entities if isinstance(entities, list) else []

        relations_resp = await client.get(
            f"{base_url}/rest/v1/{_RELATIONS_TABLE}",
            headers=_svc_headers(),
            params={"select": "from_entity_id,to_entity_id,relation_type", "limit": str(limit)},
        )
        relations_resp.raise_for_status()
        relations = relations_resp.json()
        relations = relations if isinstance(relations, list) else []

        return entities, relations
    except Exception:
        logger.exception("knowledge_graph: failed to get_entities_and_relations")
        return [], []


# Phase B9 -> B7 integration: pure text matching, no LLM, no I/O.
_MAX_HINT_RELATIONS = 3


def build_entity_hint(
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    query_text: str,
) -> str | None:
    """Return a short, optional hint string listing known relations for
    any entity whose name is contained in `query_text` (plain substring
    match — no LLM). Fed into multihop_search.decompose_query() as an
    additional optional hint, the same mechanism B7 already uses for
    recent topic labels (_format_topic_hint) — see this module's docstring
    for why this adds no new LLM call.
    """
    if not entities or not relations or not query_text:
        return None

    cleaned_query = query_text.strip()
    if not cleaned_query:
        return None

    entities_by_id = {e["id"]: e for e in entities if e.get("id")}
    matched_ids = {
        e["id"] for e in entities
        if e.get("name") and str(e["name"]) in cleaned_query
    }
    if not matched_ids:
        return None

    lines: list[str] = []
    for relation in relations:
        if len(lines) >= _MAX_HINT_RELATIONS:
            break
        from_id = relation.get("from_entity_id")
        to_id = relation.get("to_entity_id")
        if from_id not in matched_ids and to_id not in matched_ids:
            continue
        from_entity = entities_by_id.get(from_id)
        to_entity = entities_by_id.get(to_id)
        if not from_entity or not to_entity:
            continue
        relation_type = relation.get("relation_type") or ""
        lines.append(f"{from_entity['name']} —{relation_type}— {to_entity['name']}")

    if not lines:
        return None
    return "既知の関連(参考、無理に使う必要はない): " + "; ".join(lines)
