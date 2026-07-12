from __future__ import annotations

# Phase B2: episodic memory (this module) vs semantic memory
# (user_fact_data.py's user_fact_items) role separation.
#
# sigmaris_experience holds "what happened at a point in time" — a specific
# turn where 海星さん got stuck on something and resolved it, a prediction
# Sigmaris made, a proposal that succeeded or failed. It is inherently
# time-bound and situational: the same underlying topic can appear across
# many rows as the situation evolves (e.g. "stuck on X" then later
# "resolved X with Y"), and old rows are never rewritten to reflect later
# developments.
#
# user_fact_items holds "what is permanently true" — a fact that, once
# recorded, is expected to keep holding until something actively
# contradicts or supersedes it (memory_validator.py's decay/contradiction
# logic), not something that naturally has an end date the way an episode
# does. The two tables must not duplicate the same information: an episode
# ("海星さんがX機能の実装で詰まり、Yという方法で解決した") stays episodic
# unless consolidate_episodic_memory() judges that a *permanent* fact can be
# derived from it ("海星さんはXという技術に慣れていない") — and even then,
# the episode row is left in place untouched, not deleted or overwritten;
# the fact row is a new, separate record with source_experience_ids
# pointing back at the episode(s) it came from.

import json
import logging
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_search import search_relevant_memories
from app.services.supabase_rest import _get_client, _require_supabase_config, get_current_user

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_experience"

_VALID_TYPES = frozenset({"success", "failure", "unresolved"})
_VALID_CATEGORIES = frozenset({"proposal", "reflection", "research", "interaction", "prediction"})

# user_fact_items.category check constraint
# (202606300024_chatgpt_history_import.sql) — kept in sync manually since
# there is no way to introspect a CHECK constraint from here.
_VALID_FACT_CATEGORIES = frozenset({
    "profile", "health", "lifestyle", "environment", "devices", "preferences",
    "preference", "relationships", "finance", "goals", "work", "personality",
    "timeline",
})

# Phase B2: don't attempt consolidation below this many total episodes —
# mirrors decision_log.py's _MIN_DECISIONS_FOR_ANALYSIS reasoning (nothing
# to find a *recurring* pattern across yet).
_MIN_EXPERIENCES_FOR_CONSOLIDATION = 3
# A candidate fact needs evidence from at least this many *distinct*
# episodes to be promoted, UNLESS the LLM explicitly flags it as a
# single_episode_exception (a one-off event that is nonetheless obviously
# permanent, e.g. "moved to Sapporo") — see _CONSOLIDATE_PROMPT.
_MIN_SUPPORTING_EXPERIENCES = 2

# How many existing facts (Phase B1 hybrid search) to show
# consolidate_episodic_memory()'s LLM call as candidates for category/key
# reuse. Same underlying flaw as decision_log.py's facts_context (see
# docs/sigmaris/bug_inventory.md 9 section) — _CONSOLIDATE_PROMPT previously
# showed the LLM *no* existing user_fact_items at all, so a promoted fact
# could easily land under a newly-invented category/key that duplicates one
# already there (memory_duplicate_rate, bug_inventory.md 2.2/7). Unlike the
# per-turn detectors, this runs over up to 100 episodes in one batch call, so
# there's no single natural "current turn" query — the episode titles in the
# batch are concatenated into one query instead (see
# _build_existing_facts_context_for_consolidation). A single shared search
# across a topically-diverse batch won't surface every existing fact
# relevant to every individual candidate as precisely as a per-turn query
# would, but it's a direct, low-risk improvement over showing nothing.
_CONSOLIDATION_FACTS_SEARCH_LIMIT = 20

_DETECT_EPISODE_SYSTEM = (
    "あなたはシグマリスのエピソード記憶検出システムです。会話のやり取りに、"
    "後から参照する価値のある「出来事」(達成・失敗・未解決の問題・重要な気"
    "づき・予測など)が含まれるかを判定します。雑談・単純な質問応答・確認の"
    "みのやり取りには反応しないでください。必ず有効なJSONのみを返してくだ"
    "さい。"
)

_DETECT_EPISODE_PROMPT = """以下の直近のやり取りを確認してください。

## 直近のやり取り
{transcript}

---
このやり取りに、後から参照する価値のある「出来事」が明確に含まれる場合の
み(例:海星さんが何かに詰まって解決した、明確な失敗があった、まだ解決し
ていない問題が残った、重要な気づき・予測があった)、以下のJSONを出力して
ください:
{{
  "has_episode": true,
  "experience_type": "success または failure または unresolved",
  "category": "proposal, reflection, research, interaction, prediction のいずれか",
  "title": "出来事の要約（40文字以内）",
  "description": "出来事の詳しい内容",
  "outcome": "結果（あれば、なければnull）",
  "lesson": "そこから得られる教訓・注意点（あれば、なければnull）"
}}

含まれない場合（雑談・単純な質問応答・確認のみ等）は以下のみ返してくださ
い:
{{"has_episode": false}}"""

_CONSOLIDATE_SYSTEM = (
    "あなたはシグマリスの記憶統合システムです。エピソード記憶(出来事の記"
    "録)を振り返り、そこから恒久的に成り立つ事実として意味記憶に昇格させる"
    "べき内容を抽出します。複数のエピソードに共通するパターンを優先し、単"
    "発のエピソードは明らかに恒久的な事実である場合のみ例外的に採用してく"
    "ださい。必ず有効なJSONのみを返してください。"
)

_CONSOLIDATE_PROMPT = """以下は海星さんに関するエピソード記憶です(sigmaris_experience)。「その時々
に起きた出来事」の記録であり、そこから「恒久的に成り立つ事実」を抽出する
のが目的です。

## エピソード記憶({n}件)
{experiences}

## 既に記録されている関連事実(参考。今回のエピソード群に関連度が高い順)
{existing_facts_context}

---
以下の基準で、意味記憶(user_fact_items)に昇格させるべき恒久的な事実を抽出
してください。

**採用基準:**
1. 複数のエピソードに共通するパターンとして観測できる場合(推奨): 裏付け
   となるエピソードが最低2件以上必要です。
2. 単発のエピソードだが、内容自体が明らかに恒久的な事実である場合(例:
   「海星さんは札幌に引っ越した」「海星さんは転職した」のような一度きりだ
   が長期間成り立ち続ける事実)は、例外的に1件でも採用してよいですが、
   single_episode_exception を true にし、なぜ恒久的だと判断したかを
   reason に明記してください。
3. 「その場限りの状態」(例:「今日は疲れている」「今この作業に詰まってい
   る」)は絶対に恒久的事実として抽出しないでください。それはエピソード記
   憶のままにしておくべき内容です。
4. 上記の既存事実と実質的に同じ内容(表現が違うだけの言い換えを含む)を
   抽出する場合は、絶対に新しいcategory/keyを作らず、既存と全く同じ
   category・keyをそのまま使ってください。新しいcategory/keyを作ってよい
   のは、既存のどれとも異なる、本当に新しい情報の場合だけです。

**有効なcategory:** profile, health, lifestyle, environment, devices,
preferences, relationships, finance, goals, work, personality, timeline

以下のJSON形式で出力してください:
{{
  "facts": [
    {{
      "category": "...",
      "key": "snake_caseの短いキー",
      "value": "事実の内容",
      "confidence": 0.8,
      "reason": "なぜこれを恒久的な事実だと判断したか",
      "single_episode_exception": false,
      "supporting_experience_ids": ["id1", "id2", "..."]
    }}
  ]
}}
何も見つからなければ {{"facts": []}} を返してください。"""

_ANALYZE_SYSTEM = "あなたはシグマリスの自己分析システムです。経験パターンを分析し、改善点を日本語で簡潔に返してください。必ず有効なJSONのみを返してください。"

_ANALYZE_PROMPT = """以下のシグマリスの経験記録を分析し、パターンと改善点を抽出してください。

## 直近の経験（{n}件）
{experiences}

---
以下のJSONを出力してください:
{{
  "success_patterns": ["成功パターン1", "成功パターン2"],
  "failure_patterns": ["失敗パターン1", "失敗パターン2"],
  "improvement_suggestions": ["改善提案1", "改善提案2"],
  "adoption_rate_avg": 0.0,
  "confidence_delta_avg": 0.0
}}"""


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


async def record_experience(
    *,
    experience_type: str,
    category: str,
    title: str,
    description: str | None = None,
    context: dict[str, Any] | None = None,
    outcome: str | None = None,
    lesson: str | None = None,
    adoption_rate: float | None = None,
    confidence_delta: float = 0.0,
    related_fact_ids: list[str] | None = None,
    thread_id: str | None = None,
    invocation_id: str | None = None,
) -> str | None:
    """Insert a new experience record. Returns the created row ID or None.

    thread_id/invocation_id (Phase B4 provenance) are optional: this
    function is currently only reachable via the external-agent route
    POST /agent/experience/record, and no caller of that route is known to
    supply a chat-turn context today — see phase_b4_report.md section 1 for
    why this is documented as "ready to receive provenance" rather than
    "actively populated", unlike user_fact_items/sigmaris_decision_log.
    """
    try:
        if experience_type not in _VALID_TYPES:
            logger.warning("experience_layer: invalid type=%s", experience_type)
            return None
        if category not in _VALID_CATEGORIES:
            logger.warning("experience_layer: invalid category=%s", category)
            return None

        payload: dict[str, Any] = {
            "experience_type": experience_type,
            "category": category,
            "title": title,
            "confidence_delta": confidence_delta,
        }
        if description is not None:
            payload["description"] = description
        if context is not None:
            payload["context"] = context
        if outcome is not None:
            payload["outcome"] = outcome
        if lesson is not None:
            payload["lesson"] = lesson
        if adoption_rate is not None:
            payload["adoption_rate"] = max(0.0, min(1.0, adoption_rate))
        if related_fact_ids is not None:
            payload["related_fact_ids"] = related_fact_ids
        if thread_id is not None:
            payload["thread_id"] = thread_id
        if invocation_id is not None:
            payload["invocation_id"] = invocation_id

        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.post(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            json=payload,
        )
        r.raise_for_status()
        rows = r.json()
        if isinstance(rows, list) and rows:
            rid = rows[0].get("id")
            logger.info("experience_layer: recorded %s/%s id=%s", experience_type, category, rid)
            return rid
        return None
    except Exception:
        logger.exception("experience_layer: failed to record_experience title=%s", title)
        return None


async def get_recent_experiences(
    limit: int = 30,
    *,
    experience_type: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent experience rows, optionally filtered."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        params: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
        if experience_type:
            params["experience_type"] = f"eq.{experience_type}"
        if category:
            params["category"] = f"eq.{category}"
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params=params,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("experience_layer: failed to get_recent_experiences")
        return []


async def get_experiences_by_ids(experience_ids: list[str]) -> list[dict[str, Any]]:
    """Return sigmaris_experience rows for a specific set of ids.

    Phase R-1 (docs/sigmaris/phase_r_report.md): the dereferencing step
    cycle_trace.py uses to turn user_fact_items.source_experience_ids into
    the actual Experience-stage rows a consolidated fact came from.
    """
    ids = [str(eid) for eid in experience_ids if eid]
    if not ids:
        return []
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"id": f"in.({','.join(ids)})"},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("experience_layer: failed to get_experiences_by_ids")
        return []


async def analyze_patterns() -> dict[str, Any] | None:
    """Weekly scheduled: LLM analysis of recent experience patterns."""
    try:
        experiences = await get_recent_experiences(limit=50)
        if not experiences:
            logger.info("experience_layer: no experiences to analyze")
            return None

        summary_lines = []
        for e in experiences[:30]:
            summary_lines.append(
                f"[{e.get('experience_type')}][{e.get('category')}] {e.get('title')} "
                f"outcome={e.get('outcome', 'N/A')} lesson={e.get('lesson', 'N/A')}"
            )
        experiences_text = "\n".join(summary_lines)

        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": _ANALYZE_SYSTEM},
                {"role": "user", "content": _ANALYZE_PROMPT.format(
                    n=len(experiences),
                    experiences=experiences_text,
                )},
            ],
            temperature=0.3,
            max_tokens=512,
            json_mode=True,
        )
        analysis = json.loads(raw) if isinstance(raw, str) else raw
        logger.info("experience_layer: pattern analysis done patterns=%s", list(analysis.keys()))
        return analysis if isinstance(analysis, dict) else None
    except Exception:
        logger.exception("experience_layer: failed to analyze_patterns")
        return None


async def mark_resolved(experience_id: str, *, outcome: str, lesson: str | None = None) -> bool:
    """Update an unresolved experience to success or failure."""
    try:
        payload: dict[str, Any] = {"outcome": outcome, "experience_type": "success"}
        if lesson:
            payload["lesson"] = lesson
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            params={"id": f"eq.{experience_id}"},
            json=payload,
        )
        r.raise_for_status()
        logger.info("experience_layer: resolved id=%s", experience_id)
        return True
    except Exception:
        logger.exception("experience_layer: failed to mark_resolved id=%s", experience_id)
        return False


def _format_transcript(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = "海星" if message.get("role") == "user" else "シグマリス"
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def detect_and_record_episode(
    *,
    messages: list[dict[str, str]],
    thread_id: str | None = None,
    invocation_id: str | None = None,
) -> str | None:
    """Fire-and-forget: ask the LLM whether the just-completed turn contains
    an episodic event worth remembering (not small talk / a plain Q&A).
    Mirrors decision_log.detect_and_record_decision()'s shape exactly —
    same fire-and-forget entry point (orchestrator's _cognitive_layer_bg),
    same per-turn-scoped transcript, same has_x/false-by-default contract.

    `messages` should be just the current turn (the latest user message plus
    the assistant's reply) — not the full cross-thread session window — so
    the same earlier exchange isn't re-recorded as "a new episode" on every
    later turn it happens to still be in context for.
    """
    try:
        transcript = _format_transcript(messages)
        if not transcript:
            return None

        router = get_llm_router()
        raw = await router.chat(
            TaskType.EPISODE_DETECTION,
            [
                {"role": "system", "content": _DETECT_EPISODE_SYSTEM},
                {"role": "user", "content": _DETECT_EPISODE_PROMPT.format(transcript=transcript)},
            ],
            temperature=0.1,
            max_tokens=400,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict) or not parsed.get("has_episode"):
            return None

        experience_type = parsed.get("experience_type")
        if experience_type not in _VALID_TYPES:
            experience_type = "unresolved"
        category = parsed.get("category")
        if category not in _VALID_CATEGORIES:
            category = "interaction"
        title = str(parsed.get("title") or "").strip()[:200] or transcript[:80]
        description = parsed.get("description")
        outcome = parsed.get("outcome")
        lesson = parsed.get("lesson")

        return await record_experience(
            experience_type=experience_type,
            category=category,
            title=title,
            description=description if isinstance(description, str) and description.strip() else None,
            outcome=outcome if isinstance(outcome, str) and outcome.strip() else None,
            lesson=lesson if isinstance(lesson, str) and lesson.strip() else None,
            thread_id=thread_id,
            invocation_id=invocation_id,
        )
    except Exception:
        logger.exception("experience_layer: failed to detect_and_record_episode")
        return None


async def _build_existing_facts_context_for_consolidation(
    experiences: list[dict[str, Any]], jwt: str
) -> str:
    """Facts context for _CONSOLIDATE_PROMPT (Phase B1 hybrid search), so the
    consolidation LLM can reuse an existing category/key instead of
    fragmenting the same fact across differently-named rows — see
    _CONSOLIDATION_FACTS_SEARCH_LIMIT's comment for the query-strategy
    rationale. Best-effort: any failure here (search error, missing
    user_id) falls back to "no existing facts" context rather than blocking
    consolidation entirely."""
    query = " / ".join(
        str(e.get("title")).strip()
        for e in experiences
        if isinstance(e.get("title"), str) and e.get("title").strip()
    )[:2000]
    if not query:
        return "（なし）"

    try:
        user = await get_current_user(jwt)
        user_id = user.get("id")
        if not isinstance(user_id, str):
            return "（なし）"

        results = await search_relevant_memories(
            query, user_id, limit=_CONSOLIDATION_FACTS_SEARCH_LIMIT, jwt=jwt
        )
    except Exception:
        logger.debug(
            "experience_layer: existing-facts search failed, proceeding without it",
            exc_info=True,
        )
        return "（なし）"

    lines = [
        f"- {row.get('category')}/{row.get('key')}: {row.get('value')}"
        for row in results
        if isinstance(row.get("category"), str) and isinstance(row.get("key"), str) and row.get("value")
    ]
    return "\n".join(lines) if lines else "（なし）"


async def consolidate_episodic_memory(jwt: str) -> dict[str, Any]:
    """Sunday 4:55 AM scheduled (right after adoption_count_recompute, before
    narrative_generate): review recent episodic memory and promote recurring
    (or exceptionally, single-but-clearly-permanent) patterns into
    user_fact_items.

    Requires a live user JWT (unlike this module's other weekly-batch-style
    functions) because it writes through upsert_fact_item()'s RPC, which
    runs SECURITY INVOKER against auth.uid() — appropriate here since a
    *new* semantic fact is being created, and user_fact_items' RLS is
    per-user by design (unlike sigmaris_experience/decision_log/preference
    patterns, which are service-role-only global tables). The scheduler
    wrapper resolves this the same way _memory_embed/_memory_validate
    already do (get_sigmaris_jwt()).

    Re-scans the most recent 100 episodes every run rather than tracking a
    "already consolidated" cursor — upsert_fact_item is idempotent per
    (user_id, category, key), so re-deriving the same fact from the same
    episodes just refreshes it rather than duplicating it. This mirrors
    decision_log.py's extract_preference_patterns(), which re-scans the same
    window of decisions on every weekly run for the same reason.
    """
    result: dict[str, Any] = {
        "analyzed": 0,
        "candidates_found": 0,
        "facts_upserted": 0,
        "errors": 0,
        "insufficient_data": False,
    }
    try:
        experiences = await get_recent_experiences(limit=100)
        result["analyzed"] = len(experiences)
        if len(experiences) < _MIN_EXPERIENCES_FOR_CONSOLIDATION:
            result["insufficient_data"] = True
            logger.info(
                "experience_layer: consolidation skipped — only %d experiences "
                "(need >= %d) to look for a recurring pattern",
                len(experiences), _MIN_EXPERIENCES_FOR_CONSOLIDATION,
            )
            return result

        experience_ids = {e.get("id") for e in experiences if e.get("id")}
        lines = [
            f"- id={e.get('id')} type={e.get('experience_type')} category={e.get('category')} "
            f"title={e.get('title')} description={(e.get('description') or 'N/A')[:150]} "
            f"outcome={(e.get('outcome') or 'N/A')[:150]} lesson={(e.get('lesson') or 'N/A')[:150]}"
            for e in experiences
        ]
        existing_facts_context = await _build_existing_facts_context_for_consolidation(
            experiences, jwt
        )

        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": _CONSOLIDATE_SYSTEM},
                {"role": "user", "content": _CONSOLIDATE_PROMPT.format(
                    n=len(experiences), experiences="\n".join(lines),
                    existing_facts_context=existing_facts_context,
                )},
            ],
            temperature=0.2,
            max_tokens=1200,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        candidates = parsed.get("facts") if isinstance(parsed, dict) else None
        if not isinstance(candidates, list):
            candidates = []
        result["candidates_found"] = len(candidates)

        from app.services.user_fact_data import upsert_fact_item  # noqa: PLC0415

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            category = str(candidate.get("category") or "").strip()
            key = str(candidate.get("key") or "").strip()
            value = candidate.get("value")
            if category not in _VALID_FACT_CATEGORIES or not key or not isinstance(value, str) or not value.strip():
                continue

            raw_ids = candidate.get("supporting_experience_ids")
            # Only trust ids that actually exist among the episodes we sent
            # the LLM — never take an LLM-invented id at face value (same
            # defensive pattern as decision_log.extract_preference_patterns).
            supporting_ids = list(dict.fromkeys(
                eid for eid in (raw_ids if isinstance(raw_ids, list) else [])
                if isinstance(eid, str) and eid in experience_ids
            ))
            is_exception = bool(candidate.get("single_episode_exception"))
            has_enough_evidence = len(supporting_ids) >= _MIN_SUPPORTING_EXPERIENCES
            has_exception_evidence = is_exception and len(supporting_ids) >= 1
            if not (has_enough_evidence or has_exception_evidence):
                logger.debug(
                    "experience_layer: discarding consolidation candidate '%s/%s' — only %d "
                    "verifiable supporting episodes (need >= %d, or single_episode_exception "
                    "with >= 1)",
                    category, key, len(supporting_ids), _MIN_SUPPORTING_EXPERIENCES,
                )
                continue

            confidence = candidate.get("confidence")
            confidence = max(0.0, min(1.0, float(confidence))) if isinstance(confidence, (int, float)) else 0.7
            reason = str(candidate.get("reason") or "episode_consolidation")[:500]

            try:
                await upsert_fact_item(
                    jwt,
                    category=category,
                    key=key,
                    value=value.strip(),
                    confidence=confidence,
                    source="episode_consolidation",
                    reason=reason,
                    source_experience_ids=supporting_ids,
                )
                result["facts_upserted"] += 1
            except Exception:
                logger.exception(
                    "experience_layer: failed to upsert consolidated fact %s/%s", category, key
                )
                result["errors"] += 1

        logger.info(
            "experience_layer: consolidation done analyzed=%d found=%d upserted=%d",
            result["analyzed"], result["candidates_found"], result["facts_upserted"],
        )
        return result
    except Exception:
        logger.exception("experience_layer: failed to consolidate_episodic_memory")
        result["errors"] += 1
        return result
