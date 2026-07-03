# 役割: Phase C-mini評価テストセットの生成(LLMによる逆生成方式)。
#
# user_fact_items(事実)とsigmaris_decision_log(決定記録)から、「この記憶を
# 正解とする自然な質問文」をLLMに生成させ、backend/eval/testset.jsonの形式で
# 保存する。実行は backend/scripts/generate_eval_testset.py から行う。
#
# 【重要】ここで生成される質問文・正解ラベルはLLMによる自動生成であり、
# 誤り・不自然な質問が混ざる可能性がある。将来的に海星さんが
# backend/eval/testset.json を直接編集してレビュー・修正できるよう、
# 各エントリに "reviewed": false を持たせている(このスクリプトを再実行しても
# reviewed: true のエントリは上書きしない設計、詳細はbuild_testset()参照)。
#
# 決定記録(sigmaris_decision_log)は現状ベクトル埋め込みを持たず、
# search_relevant_memories() (=search_fact_memory RPC) が検索するのは
# user_fact_items のみである。そのため決定由来の設問であっても、採点時の
# 正解(expected_fact_keys)は「その決定が参照したuser_fact_items」
# (decision.memory_refs)に解決してから使う。memory_refsが空の決定は
# 検証不能なので採用しない。(判断根拠はphase_c_mini_report.md参照)

from __future__ import annotations

import json
import logging
import random
from datetime import UTC, datetime
from typing import Any

from app.services.decision_log import get_recent_decisions
from app.services.local_llm import TaskType, get_llm_router
from app.services.user_fact_data import get_fact_items

logger = logging.getLogger(__name__)

TESTSET_SCHEMA_VERSION = 1

_FACT_QUESTION_SYSTEM = (
    "あなたはシグマリスの評価用テストセット作成システムです。"
    "与えられた事実を答えとする、自然な日本語の質問文を1つ作成します。"
    "事実の文言をそのまま繰り返さず、海星さん本人が実際に聞きそうな聞き方に"
    "してください。必ず有効なJSONのみを返してください。"
)

_FACT_QUESTION_PROMPT = """以下の事実を答えとする質問文を1つ作ってください。

category: {category}
key: {key}
value: {value}

以下のJSON形式のみで返してください:
{{"question": "質問文"}}"""

_DECISION_QUESTION_SYSTEM = (
    "あなたはシグマリスの評価用テストセット作成システムです。"
    "与えられた過去の決定事項について、その内容を尋ねる自然な日本語の質問文を"
    "1つ作成します。必ず有効なJSONのみを返してください。"
)

_DECISION_QUESTION_PROMPT = """以下の過去の決定事項について、その内容を尋ねる質問文を1つ作ってください。

title: {title}
outcome: {outcome}
reason: {reason}

以下のJSON形式のみで返してください:
{{"question": "質問文"}}"""


def _fact_key(item: dict[str, Any]) -> str:
    return f"{item.get('category')}/{item.get('key')}"


async def _generate_question(system: str, prompt: str) -> str | None:
    try:
        router = get_llm_router()
        raw = await router.chat(
            TaskType.EVAL_GENERATION,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=150,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        question = parsed.get("question") if isinstance(parsed, dict) else None
        return question.strip() if isinstance(question, str) and question.strip() else None
    except Exception:
        logger.exception("testset_gen: question generation failed")
        return None


async def _build_fact_entries(
    fact_items: list[dict[str, Any]], *, limit: int, rng: random.Random
) -> list[dict[str, Any]]:
    candidates = [item for item in fact_items if item.get("value")]
    sample = rng.sample(candidates, k=min(limit, len(candidates)))

    entries: list[dict[str, Any]] = []
    for item in sample:
        question = await _generate_question(
            _FACT_QUESTION_SYSTEM,
            _FACT_QUESTION_PROMPT.format(
                category=item.get("category"), key=item.get("key"), value=item.get("value")
            ),
        )
        if not question:
            continue
        entries.append(
            {
                "id": f"fact-{item.get('id')}",
                "question": question,
                "source": "fact",
                "expected_fact_keys": [_fact_key(item)],
                "notes": None,
                "generated_by": "llm",
                "reviewed": False,
            }
        )
    return entries


async def _build_decision_entries(
    decisions: list[dict[str, Any]],
    fact_id_to_key: dict[str, str],
    *,
    limit: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    # memory_refsが空の決定は、search_relevant_memoriesで採点しようがないため除外する
    # (sigmaris_decision_logはベクトル検索の対象外 — 詳細はモジュールdocstring参照)。
    candidates = []
    for decision in decisions:
        refs = decision.get("memory_refs") or []
        keys = [fact_id_to_key[ref] for ref in refs if ref in fact_id_to_key]
        if keys:
            candidates.append((decision, keys))

    sample = rng.sample(candidates, k=min(limit, len(candidates)))

    entries: list[dict[str, Any]] = []
    for decision, keys in sample:
        question = await _generate_question(
            _DECISION_QUESTION_SYSTEM,
            _DECISION_QUESTION_PROMPT.format(
                title=decision.get("title"),
                outcome=decision.get("outcome") or "(なし)",
                reason=decision.get("reason") or "(なし)",
            ),
        )
        if not question:
            continue
        entries.append(
            {
                "id": f"decision-{decision.get('id')}",
                "question": question,
                "source": "decision",
                "expected_fact_keys": keys,
                "notes": f"source_decision_title={decision.get('title')}",
                "generated_by": "llm",
                "reviewed": False,
            }
        )
    return entries


async def build_testset(
    *,
    jwt: str,
    user_id: str,
    max_fact_questions: int = 20,
    max_decision_questions: int = 10,
    seed: int = 42,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a fresh testset from live user_fact_items / sigmaris_decision_log.

    If `existing` is provided, entries with reviewed=True are carried over
    unchanged (human review is never silently discarded by a re-run) and
    excluded from re-sampling by id.
    """
    rng = random.Random(seed)

    fact_items = await get_fact_items(jwt, active_only=True)
    fact_id_to_key = {item["id"]: _fact_key(item) for item in fact_items if item.get("id")}
    decisions = [d for d in await get_recent_decisions(limit=100) if not d.get("superseded_by")]

    reviewed_entries: list[dict[str, Any]] = []
    reviewed_ids: set[str] = set()
    if existing:
        for entry in existing.get("entries", []):
            if entry.get("reviewed"):
                reviewed_entries.append(entry)
                reviewed_ids.add(entry["id"])

    fact_entries = await _build_fact_entries(fact_items, limit=max_fact_questions, rng=rng)
    decision_entries = await _build_decision_entries(
        decisions, fact_id_to_key, limit=max_decision_questions, rng=rng
    )

    generated_entries = [
        entry
        for entry in (fact_entries + decision_entries)
        if entry["id"] not in reviewed_ids
    ]

    return {
        "schema_version": TESTSET_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": "llm",
        "user_id": user_id,
        "entries": reviewed_entries + generated_entries,
    }
