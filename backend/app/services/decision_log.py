from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_search import search_relevant_memories
from app.services.supabase_rest import _get_client, _require_supabase_config, get_current_user
from app.services.user_fact_data import build_facts_context

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_decision_log"
_PATTERNS_TABLE = "sigmaris_user_preference_patterns"
_FACT_ITEMS_TABLE = "user_fact_items"

_VALID_TYPES = frozenset({"proposal", "refusal", "notification", "action", "policy_change"})

# How many existing facts (Phase B1 hybrid search, ranked by relevance to the
# latest user turn) to show the decision-detection LLM as candidates for
# related_fact_keys. See docs/sigmaris/bug_inventory.md 2.4/9 for why this
# exists: facts_context used to be build_facts_context(fact_items, top_n=15)
# — the 15 GLOBALLY most important facts by importance*confidence, regardless
# of what the current decision is actually about. With 500+ active facts,
# the one a given decision actually concerns is very unlikely to be in that
# fixed top-15 list, so related_fact_keys came back empty essentially every
# time (confirmed against production data: 42/42 sigmaris_decision_log rows
# had empty memory_refs). Searching for facts relevant to *this* turn (same
# fix pattern already applied to memory_extractor.py) makes the fact the
# decision is actually about far more likely to be visible to the LLM.
_RELEVANT_FACTS_SEARCH_LIMIT = 15

# Phase B14: don't even attempt extraction below this many total decisions
# (there's nothing to find a *recurring* pattern across).
_MIN_DECISIONS_FOR_ANALYSIS = 3
# A candidate pattern needs evidence from at least this many *distinct*
# decisions to be persisted — a single decision is never enough to
# conclude "this is how 海星さん thinks" (explicit task requirement).
_MIN_SUPPORTING_DECISIONS = 2

# Phase B13: how many recent decisions recompute_adoption_counts() scans.
# A single generous page rather than full pagination (like
# update_fact_embeddings()'s batch loop) — deliberately scoped down given
# current decision volume is low; see phase_b13_report.md section 1.
_ADOPTION_RECOMPUTE_DECISION_LIMIT = 500

_DETECT_SYSTEM = (
    "あなたはシグマリスの意思決定検出システムです。会話のやり取りに、決定・"
    "方針転換・重要な選択が含まれるかを判定します。雑談・確認・単純な質問"
    "応答・情報の読み上げには反応しないでください。必ず有効なJSONのみを返"
    "してください。"
)

_DETECT_PROMPT = """以下の直近のやり取りを確認してください。

## 直近のやり取り
{transcript}

## 海星さんの既知の事実（参考。関連があれば related_fact_keys に category/key の形式で引用してよい）
{facts_context}

## 現在アクティブな直近の決定事項（{active_count}件。今回の内容がこれらのいずれかを置き換える場合はそのidを返す）
{active_decisions}

---
このやり取りに、決定・方針転換・重要な選択（例:「AではなくBにする」「〜す
ることにした」「今後は〜する」）が明確に含まれる場合のみ、以下のJSONを出力
してください。

decision_typeは必ず次の5種類のいずれか一つとし、自由記述は禁止します:
- policy_change: 海星さん自身が「今後はこうする」と方針・ルールを決定または変更した（海星さん本人の決定）
- proposal: シグマリスが海星さんに何かを提案した（まだ確定していない、承認待ちの提案）
- refusal: シグマリスが海星さんの提案・依頼を断った、または実行しないことにした
- action: シグマリスが実際に何らかの操作・行動を実行した（カレンダー登録、調査の実行など、方針決定ではなく具体的な処理の実施）
- notification: シグマリスが海星さんに何かを知らせた・報告した（決定でも行動でもない単純な通知。他の4つのいずれにも該当しない場合の最終手段としてのみ選ぶこと）

{{
  "has_decision": true,
  "decision_type": "policy_change | proposal | refusal | action | notification のいずれか一つ",
  "title": "決定内容の要約（40文字以内）",
  "reason": "なぜその決定に至ったか（会話内容から）",
  "outcome": "決定の具体的内容",
  "related_fact_keys": ["category/key", "..."],
  "supersedes_decision_id": "置き換える決定のid、なければnull"
}}

含まれない場合（雑談・単純な質問・確認のみ・情報照会のみ等）は以下のみ返し
てください:
{{"has_decision": false}}"""

_ANALYZE_SYSTEM = "あなたはシグマリスの意思決定分析システムです。過去の判断パターンを分析し、改善点を日本語で返してください。必ず有効なJSONのみを返してください。"

_ANALYZE_PROMPT = """以下のシグマリスの意思決定ログを分析してください。

## 直近の決定（{n}件）
{decisions}

---
以下のJSONを出力してください:
{{
  "common_patterns": ["よく見られるパターン1", "パターン2"],
  "proposal_rate": 0.0,
  "refusal_rate": 0.0,
  "improvement_suggestions": ["改善提案1", "改善提案2"],
  "notes": "全体的な傾向メモ"
}}"""

# Phase B14: distinct from _ANALYZE_PROMPT above. analyze_decision_patterns()
# analyzes Sigmaris's OWN behavior distribution (proposal_rate/refusal_rate —
# how often *Sigmaris* proposes vs refuses). This instead extracts 海星さん's
# own judgment axes/values from decision content — a different subject and
# a different, more conservative extraction contract (never conclude from
# one data point).
_EXTRACT_PREFERENCE_SYSTEM = (
    "あなたはシグマリスの判断傾向分析システムです。海星さんの過去の決定記"
    "録から、複数の決定に共通する判断傾向(判断軸)を抽出します。単発の決"
    "定からは絶対に傾向を導かないでください。必ず有効なJSONのみを返してく"
    "ださい。"
)

_EXTRACT_PREFERENCE_PROMPT = """以下は海星さんに関する決定記録です(sigmaris_decision_log)。
decision_type が policy_change のものは、海星さん自身が実際に下した決定・
方針転換を表します。それ以外(proposal/refusal/notification/action)はシ
グマリス側の行動記録ですが、reasonやoutcomeに海星さんの価値観が読み取れる
場合は参考にしてよいです。

## 決定記録({n}件)
{decisions}

## 参考: 関連度の高い既知の記憶(判断の背景理解に使ってよい)
{relevant_facts_context}

## 既に登録されている判断傾向(参考。実質的に同じ傾向であれば、新しい
pattern_keyを作らず必ずこの一覧のpattern_keyをそのまま使うこと)
{existing_patterns_context}

---
これらの決定に共通する、海星さんの判断傾向(判断軸)を抽出してください。

**重要な制約:**
- 1件の決定だけを根拠に傾向を導き出さないこと。同じ傾向を裏付ける決定が
  最低2件以上ないかぎり、その傾向は出力しないこと
- 根拠が薄い場合は無理に傾向を捏造せず、patternsを空リストにしてよい
- 各傾向について、根拠とした決定の id を(上記の決定記録に付与されている
  ものをそのまま)全て列挙すること
- 既に登録されている判断傾向と実質的に同じ内容(表現が違うだけの言い換えを
  含む)を抽出する場合は、絶対に新しいpattern_keyを作らず、既存の一覧にある
  pattern_keyをそのまま使うこと。新しいpattern_keyを作ってよいのは、既存の
  どれとも異なる、本当に新しい傾向の場合だけである

以下のJSON形式で出力してください:
{{
  "patterns": [
    {{
      "pattern_key": "snake_caseの短い識別子（例: prefers_speed_over_cost）",
      "pattern_statement": "傾向の説明（日本語、1文程度）",
      "supporting_decision_ids": ["id1", "id2", "..."]
    }}
  ]
}}
根拠が2件未満の傾向は絶対に含めないこと。何も見つからなければ
{{"patterns": []}} を返してください。"""


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


async def log_decision(
    *,
    decision_type: str,
    title: str,
    reason: str | None = None,
    constitution_refs: list[str] | None = None,
    memory_refs: list[str] | None = None,
    experience_refs: list[str] | None = None,
    internal_state_snapshot: dict[str, Any] | None = None,
    outcome: str | None = None,
    thread_id: str | None = None,
    invocation_id: str | None = None,
    supersedes: str | None = None,
) -> str | None:
    """Insert a decision log entry. Returns new row ID or None on failure."""
    try:
        if decision_type not in _VALID_TYPES:
            logger.warning("decision_log: invalid type=%s", decision_type)
            return None

        payload: dict[str, Any] = {
            "decision_type": decision_type,
            "title": title,
            "constitution_refs": constitution_refs or [],
            "memory_refs": memory_refs or [],
            "experience_refs": experience_refs or [],
            "internal_state_snapshot": internal_state_snapshot or {},
        }
        if reason is not None:
            payload["reason"] = reason
        if outcome is not None:
            payload["outcome"] = outcome
        if thread_id is not None:
            payload["thread_id"] = thread_id
        if invocation_id is not None:
            payload["invocation_id"] = invocation_id
        if supersedes is not None:
            payload["supersedes"] = supersedes

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
            logger.info("decision_log: logged %s title=%s id=%s", decision_type, title[:60], rid)
            return rid
        return None
    except Exception:
        logger.exception("decision_log: failed to log_decision type=%s title=%s", decision_type, title[:60])
        return None


async def mark_superseded(old_decision_id: str, new_decision_id: str) -> bool:
    """Point an old decision's superseded_by at the new decision that replaced
    it. The old row is never deleted or overwritten — this just links it
    forward so the supersede chain can be followed in either direction."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            params={"id": f"eq.{old_decision_id}"},
            json={"superseded_by": new_decision_id},
        )
        r.raise_for_status()
        logger.info("decision_log: id=%s superseded_by=%s", old_decision_id, new_decision_id)
        return True
    except Exception:
        logger.exception("decision_log: failed to mark_superseded id=%s", old_decision_id)
        return False


async def update_outcome(decision_id: str, outcome: str) -> bool:
    """Set the outcome of a previously logged decision."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.patch(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            params={"id": f"eq.{decision_id}"},
            json={"outcome": outcome},
        )
        r.raise_for_status()
        logger.info("decision_log: updated outcome id=%s", decision_id)
        return True
    except Exception:
        logger.exception("decision_log: failed to update_outcome id=%s", decision_id)
        return False


async def get_recent_decisions(
    limit: int = 30,
    *,
    decision_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent decision log entries."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        params: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
        if decision_type:
            params["decision_type"] = f"eq.{decision_type}"
        r = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params=params,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("decision_log: failed to get_recent_decisions")
        return []


async def get_decisions_by_ids(decision_ids: list[str]) -> list[dict[str, Any]]:
    """Return sigmaris_decision_log rows for a specific set of ids.

    Phase R-1 (docs/sigmaris/phase_r_report.md): the dereferencing step
    cycle_trace.py uses to turn sigmaris_user_preference_patterns.
    supporting_decision_ids into the actual decision rows a Belief-Update
    pattern was inferred from — and, one hop further, each of those
    decisions' own memory_refs into the Memory-stage facts they relied on.
    """
    ids = [str(did) for did in decision_ids if did]
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
        logger.exception("decision_log: failed to get_decisions_by_ids")
        return []


async def analyze_decision_patterns() -> dict[str, Any] | None:
    """Sunday 4:30 AM scheduled: LLM analysis of recent decision patterns."""
    try:
        decisions = await get_recent_decisions(limit=50)
        if not decisions:
            logger.info("decision_log: no decisions to analyze")
            return None

        lines = []
        type_counts: dict[str, int] = {}
        for d in decisions[:30]:
            dt = d.get("decision_type", "")
            type_counts[dt] = type_counts.get(dt, 0) + 1
            lines.append(
                f"[{dt}] {d.get('title', '')} reason={d.get('reason', 'N/A')[:80]}"
            )

        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": _ANALYZE_SYSTEM},
                {"role": "user", "content": _ANALYZE_PROMPT.format(
                    n=len(decisions),
                    decisions="\n".join(lines),
                )},
            ],
            temperature=0.3,
            max_tokens=512,
            json_mode=True,
        )
        analysis = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(analysis, dict):
            return None

        analysis["type_counts"] = type_counts
        total = len(decisions)
        analysis["proposal_rate"] = type_counts.get("proposal", 0) / total if total else 0.0
        analysis["refusal_rate"] = type_counts.get("refusal", 0) / total if total else 0.0
        logger.info("decision_log: pattern analysis done")
        return analysis
    except Exception:
        logger.exception("decision_log: failed to analyze_decision_patterns")
        return None


async def _upsert_preference_pattern(
    *,
    pattern_key: str,
    pattern_statement: str,
    supporting_decision_ids: list[str],
    analyzed_decision_count: int,
) -> str | None:
    """Insert a new pattern, or merge new evidence into an existing one
    (matched by pattern_key). Evidence accumulates across runs — a pattern
    first seen with 2 supporting decisions can grow to 5+ over subsequent
    weekly extractions without losing the earlier evidence."""
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    now = datetime.now(UTC).isoformat()

    existing_resp = await client.get(
        f"{base_url}/rest/v1/{_PATTERNS_TABLE}",
        headers=_svc_headers(),
        params={"pattern_key": f"eq.{pattern_key}", "select": "id,supporting_decision_ids"},
    )
    existing_resp.raise_for_status()
    existing_rows = existing_resp.json()
    existing = existing_rows[0] if isinstance(existing_rows, list) and existing_rows else None

    if existing:
        prior_ids = existing.get("supporting_decision_ids")
        prior_ids = prior_ids if isinstance(prior_ids, list) else []
        merged_ids = list(dict.fromkeys([*prior_ids, *supporting_decision_ids]))
        payload = {
            "pattern_statement": pattern_statement,
            "supporting_decision_ids": merged_ids,
            "evidence_count": len(merged_ids),
            "last_confirmed_at": now,
            "last_analyzed_decision_count": analyzed_decision_count,
        }
        resp = await client.patch(
            f"{base_url}/rest/v1/{_PATTERNS_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            params={"id": f"eq.{existing['id']}"},
            json=payload,
        )
    else:
        payload = {
            "pattern_key": pattern_key,
            "pattern_statement": pattern_statement,
            "supporting_decision_ids": supporting_decision_ids,
            "evidence_count": len(supporting_decision_ids),
            "last_confirmed_at": now,
            "last_analyzed_decision_count": analyzed_decision_count,
        }
        resp = await client.post(
            f"{base_url}/rest/v1/{_PATTERNS_TABLE}",
            headers=_svc_headers(prefer="return=representation"),
            json=payload,
        )

    resp.raise_for_status()
    rows = resp.json()
    return rows[0].get("id") if isinstance(rows, list) and rows else None


async def get_active_preference_patterns(limit: int = 5) -> list[dict[str, Any]]:
    """Return stored judgment/preference patterns, most-evidenced first."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_PATTERNS_TABLE}",
            headers=_svc_headers(),
            params={"order": "evidence_count.desc,last_confirmed_at.desc", "limit": str(limit)},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("decision_log: failed to get_active_preference_patterns")
        return []


async def get_preference_patterns_by_ids(pattern_ids: list[str]) -> list[dict[str, Any]]:
    """Return sigmaris_user_preference_patterns rows for a specific set of
    ids. Phase R-1 (docs/sigmaris/phase_r_report.md): the entry point
    cycle_trace.py's Belief->Memory trace uses to fetch a specific pattern
    before walking its supporting_decision_ids."""
    ids = [str(pid) for pid in pattern_ids if pid]
    if not ids:
        return []
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/{_PATTERNS_TABLE}",
            headers=_svc_headers(),
            params={"id": f"in.({','.join(ids)})"},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("decision_log: failed to get_preference_patterns_by_ids")
        return []


async def _build_relevant_facts_context_for_patterns(
    decisions: list[dict[str, Any]], *, jwt: str | None, user_id: str | None
) -> str:
    """B1 hybrid search over user_fact_items, using this batch's decision
    titles (concatenated) as the query — same query-strategy reasoning as
    experience_layer.py/knowledge_graph.py's weekly-batch fixes (no single
    "current turn" exists for a batch, so a representative summary of the
    batch's content stands in for one)."""
    query = " / ".join(
        str(d.get("title")).strip()
        for d in decisions
        if isinstance(d.get("title"), str) and d.get("title").strip()
    )[:2000]
    if not query or not jwt:
        return "（なし）"

    try:
        resolved_user_id = user_id
        if not resolved_user_id:
            user = await get_current_user(jwt)
            resolved_user_id = user.get("id")
        if not isinstance(resolved_user_id, str):
            return "（なし）"

        results = await search_relevant_memories(
            query, resolved_user_id, limit=_RELEVANT_FACTS_SEARCH_LIMIT, jwt=jwt
        )
    except Exception:
        logger.debug(
            "decision_log: relevant-facts search failed (preference patterns), "
            "proceeding without it",
            exc_info=True,
        )
        return "（なし）"

    lines = [
        f"- {row.get('category')}/{row.get('key')}: {row.get('value')}"
        for row in results
        if isinstance(row.get("category"), str) and isinstance(row.get("key"), str) and row.get("value")
    ]
    return "\n".join(lines) if lines else "（なし）"


def _build_existing_patterns_context(patterns: list[dict[str, Any]]) -> str:
    """Existing sigmaris_user_preference_patterns, shown so
    _upsert_preference_pattern()'s exact-pattern_key-match evidence
    accumulation actually has a chance to fire — this is the part that
    directly addresses pattern_key fragmentation (the B1 facts search above
    only provides background grounding; sigmaris_user_preference_patterns
    isn't indexed by B1 at all). Reuses get_active_preference_patterns()
    as-is with a larger limit than its normal "top few for hint injection"
    caller uses — its ordering (evidence_count desc) has no cooldown-style
    exclusion, so it's safe to reuse directly rather than writing a second
    fetch."""
    lines = [
        f"- {p.get('pattern_key')}: {p.get('pattern_statement')}"
        for p in patterns
        if isinstance(p.get("pattern_key"), str) and p.get("pattern_statement")
    ]
    return "\n".join(lines) if lines else "（なし）"


async def extract_preference_patterns(
    *, jwt: str | None = None, user_id: str | None = None
) -> dict[str, Any]:
    """Sunday 4:45 AM scheduled (right after analyze_decision_patterns, same
    underlying table): LLM extraction of recurring judgment patterns from
    sigmaris_decision_log, persisted to sigmaris_user_preference_patterns.

    Deliberately conservative: below _MIN_DECISIONS_FOR_ANALYSIS total
    decisions, extraction isn't even attempted (nothing to find a
    *recurring* pattern across) — this is reported as insufficient_data,
    not silently skipped, so it's visible in job logs that the feature is
    waiting on more data rather than broken.

    jwt/user_id are optional (used only for the relevant-facts B1 search);
    omitting them degrades that one context block to "（なし）" without
    blocking extraction.
    """
    result: dict[str, Any] = {
        "analyzed": 0,
        "patterns_found": 0,
        "patterns_stored": 0,
        "errors": 0,
        "insufficient_data": False,
    }
    try:
        decisions = await get_recent_decisions(limit=100)
        result["analyzed"] = len(decisions)
        if len(decisions) < _MIN_DECISIONS_FOR_ANALYSIS:
            result["insufficient_data"] = True
            logger.info(
                "decision_log: preference pattern extraction skipped — only %d decisions "
                "(need >= %d) to look for a recurring pattern",
                len(decisions), _MIN_DECISIONS_FOR_ANALYSIS,
            )
            return result

        decision_ids = {d.get("id") for d in decisions if d.get("id")}
        lines = [
            f"- id={d.get('id')} type={d.get('decision_type')} title={d.get('title')} "
            f"reason={(d.get('reason') or 'N/A')[:150]} outcome={(d.get('outcome') or 'N/A')[:150]}"
            for d in decisions
        ]
        relevant_facts_context = await _build_relevant_facts_context_for_patterns(
            decisions, jwt=jwt, user_id=user_id
        )
        existing_patterns = await get_active_preference_patterns(limit=50)
        existing_patterns_context = _build_existing_patterns_context(existing_patterns)

        router = get_llm_router()
        raw = await router.chat(
            TaskType.SELF_REFLECT,
            [
                {"role": "system", "content": _EXTRACT_PREFERENCE_SYSTEM},
                {"role": "user", "content": _EXTRACT_PREFERENCE_PROMPT.format(
                    n=len(decisions), decisions="\n".join(lines),
                    relevant_facts_context=relevant_facts_context,
                    existing_patterns_context=existing_patterns_context,
                )},
            ],
            temperature=0.2,
            max_tokens=800,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        candidates = parsed.get("patterns") if isinstance(parsed, dict) else None
        if not isinstance(candidates, list):
            candidates = []
        result["patterns_found"] = len(candidates)

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            pattern_key = str(candidate.get("pattern_key") or "").strip()
            pattern_statement = str(candidate.get("pattern_statement") or "").strip()
            if not pattern_key or not pattern_statement:
                continue

            raw_ids = candidate.get("supporting_decision_ids")
            # Only trust ids that actually exist among the decisions we sent
            # the LLM — never take an LLM-invented id at face value.
            supporting_ids = list(dict.fromkeys(
                sid for sid in (raw_ids if isinstance(raw_ids, list) else [])
                if isinstance(sid, str) and sid in decision_ids
            ))
            if len(supporting_ids) < _MIN_SUPPORTING_DECISIONS:
                logger.debug(
                    "decision_log: discarding candidate pattern '%s' — only %d verifiable "
                    "supporting decisions (need >= %d)",
                    pattern_key, len(supporting_ids), _MIN_SUPPORTING_DECISIONS,
                )
                continue

            try:
                await _upsert_preference_pattern(
                    pattern_key=pattern_key,
                    pattern_statement=pattern_statement,
                    supporting_decision_ids=supporting_ids,
                    analyzed_decision_count=len(decisions),
                )
                result["patterns_stored"] += 1
            except Exception:
                logger.exception("decision_log: failed to store preference pattern key=%s", pattern_key)
                result["errors"] += 1

        logger.info(
            "decision_log: preference pattern extraction done analyzed=%d found=%d stored=%d",
            result["analyzed"], result["patterns_found"], result["patterns_stored"],
        )
        return result
    except Exception:
        logger.exception("decision_log: failed to extract_preference_patterns")
        result["errors"] += 1
        return result


async def recompute_adoption_counts() -> dict[str, Any]:
    """Sunday 4:50 AM scheduled (right after preference_pattern_extract,
    same underlying sigmaris_decision_log source): count how many distinct
    decisions actually referenced each fact via memory_refs, and write that
    count to user_fact_items.adoption_count.

    This is the implicit-feedback signal memory_search.py's ranking uses
    (Phase B13) — "海星さん's own decisions actually relied on this fact",
    as opposed to a fact merely having been retrieved by search and never
    acted on. Positive-only by design: a fact that's never appeared in any
    memory_refs simply keeps its default adoption_count of 0 (this
    function never writes a value it would consider a penalty — see
    phase_b13_report.md section 1 for why "no evidence of adoption" must
    not be treated as "evidence of non-adoption").

    Uses service-role headers (like the rest of this module) to write
    directly to user_fact_items, bypassing that table's normal per-user JWT
    RLS path — appropriate here since this is Sigmaris's own derived
    understanding being written back, not a user-initiated edit, and it
    avoids this batch job needing to hold a live user session/JWT at all.
    """
    result: dict[str, Any] = {"decisions_scanned": 0, "facts_with_adoption": 0, "facts_updated": 0, "errors": 0}
    try:
        decisions = await get_recent_decisions(limit=_ADOPTION_RECOMPUTE_DECISION_LIMIT)
        result["decisions_scanned"] = len(decisions)

        counts: dict[str, int] = {}
        for decision in decisions:
            refs = decision.get("memory_refs")
            if not isinstance(refs, list):
                continue
            # A fact referenced twice within the *same* decision still only
            # counts once here — the signal is "how many distinct decisions
            # relied on this fact", not raw mention count.
            for fact_id in set(refs):
                if isinstance(fact_id, str) and fact_id:
                    counts[fact_id] = counts.get(fact_id, 0) + 1

        result["facts_with_adoption"] = len(counts)
        if not counts:
            logger.info("decision_log: adoption count recompute — no memory_refs found in %d decisions", len(decisions))
            return result

        base_url, _ = _require_supabase_config()
        client = await _get_client()
        for fact_id, count in counts.items():
            try:
                resp = await client.patch(
                    f"{base_url}/rest/v1/{_FACT_ITEMS_TABLE}",
                    headers=_svc_headers(prefer="return=minimal"),
                    params={"id": f"eq.{fact_id}"},
                    json={"adoption_count": count},
                )
                resp.raise_for_status()
                result["facts_updated"] += 1
            except Exception:
                logger.exception("decision_log: failed to update adoption_count fact_id=%s", fact_id)
                result["errors"] += 1

        logger.info(
            "decision_log: adoption count recompute done scanned=%d facts_with_adoption=%d updated=%d",
            result["decisions_scanned"], result["facts_with_adoption"], result["facts_updated"],
        )
        return result
    except Exception:
        logger.exception("decision_log: failed to recompute_adoption_counts")
        result["errors"] += 1
        return result


def _format_transcript(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = "海星" if message.get("role") == "user" else "シグマリス"
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _latest_user_text(messages: list[dict[str, str]]) -> str | None:
    """Most recent user-role message content, used as the search query for
    _build_relevant_facts_context() — mirrors memory_extractor.py's helper
    of the same name/purpose."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = str(message.get("content") or "").strip()
            if content:
                return content
    return None


async def _build_relevant_facts_context(
    messages: list[dict[str, str]],
    fact_items: list[dict[str, Any]] | None,
    *,
    jwt: str | None,
    user_id: str | None,
) -> str:
    """Facts context for _DETECT_PROMPT, ranked by relevance to the current
    turn (Phase B1 hybrid search) rather than by global importance — see
    _RELEVANT_FACTS_SEARCH_LIMIT's comment for why. Falls back to the
    previous global-importance-ranked build_facts_context() when jwt/user_id
    aren't available (e.g. a future caller that doesn't have them) or the
    search itself fails — this must never block decision detection."""
    query = _latest_user_text(messages)
    if jwt and query:
        try:
            resolved_user_id = user_id
            if not resolved_user_id:
                user = await get_current_user(jwt)
                resolved_user_id = user.get("id")
            if not isinstance(resolved_user_id, str):
                raise ValueError("could not resolve user_id")
            results = await search_relevant_memories(
                query, resolved_user_id, limit=_RELEVANT_FACTS_SEARCH_LIMIT, jwt=jwt
            )
            lines = [
                f"- {row.get('category')}/{row.get('key')}: {row.get('value')}"
                for row in results
                if isinstance(row.get("category"), str)
                and isinstance(row.get("key"), str)
                and row.get("value")
            ]
            if lines:
                return "\n".join(lines)
        except Exception:
            logger.debug(
                "decision_log: relevant-facts search failed, falling back to "
                "importance-ranked facts_context",
                exc_info=True,
            )
    return build_facts_context(fact_items or [], top_n=15) or "（なし）"


async def detect_and_record_decision(
    *,
    messages: list[dict[str, str]],
    fact_items: list[dict[str, Any]] | None = None,
    thread_id: str | None = None,
    invocation_id: str | None = None,
    jwt: str | None = None,
    user_id: str | None = None,
) -> str | None:
    """Fire-and-forget: ask the LLM whether the just-completed turn contains
    an actual decision or policy change (not small talk / a plain question).
    If so, record it — and if it replaces an earlier active decision, link
    the old row forward via mark_superseded() instead of touching it.

    `messages` should be just the current turn (the latest user message plus
    the assistant's reply) — not the full cross-thread session window —
    so the same earlier exchange isn't re-detected as "a new decision" on
    every subsequent turn it happens to still be in context for.

    jwt/user_id are optional and used only to look up facts relevant to this
    turn (_build_relevant_facts_context) for related_fact_keys candidates;
    omitting them falls back to the previous global-importance-ranked facts
    list, so existing callers that don't have them keep working unchanged.
    """
    try:
        transcript = _format_transcript(messages)
        if not transcript:
            return None

        facts_context = await _build_relevant_facts_context(
            messages, fact_items, jwt=jwt, user_id=user_id
        )

        active_decisions = [
            d for d in await get_recent_decisions(limit=10) if not d.get("superseded_by")
        ]
        active_lines = "\n".join(
            f"- id={d.get('id')} type={d.get('decision_type')} "
            f"title={d.get('title')} outcome={d.get('outcome') or 'N/A'}"
            for d in active_decisions
        ) or "（なし）"

        router = get_llm_router()
        raw = await router.chat(
            TaskType.DECISION_DETECTION,
            [
                {"role": "system", "content": _DETECT_SYSTEM},
                {"role": "user", "content": _DETECT_PROMPT.format(
                    transcript=transcript,
                    facts_context=facts_context,
                    active_count=len(active_decisions),
                    active_decisions=active_lines,
                )},
            ],
            temperature=0.1,
            max_tokens=400,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict) or not parsed.get("has_decision"):
            return None

        decision_type = parsed.get("decision_type")
        if decision_type not in _VALID_TYPES:
            decision_type = "policy_change"

        title = str(parsed.get("title") or "").strip()[:200] or transcript[:80]

        fact_lookup = {
            f"{item.get('category')}/{item.get('key')}": item.get("id")
            for item in (fact_items or [])
            if item.get("id")
        }
        related_keys = parsed.get("related_fact_keys")
        memory_refs = [
            fact_lookup[key]
            for key in (related_keys if isinstance(related_keys, list) else [])
            if isinstance(key, str) and key in fact_lookup
        ]

        active_ids = {d.get("id") for d in active_decisions}
        supersedes_id = parsed.get("supersedes_decision_id")
        if not isinstance(supersedes_id, str) or supersedes_id not in active_ids:
            supersedes_id = None

        from app.services.internal_state import snapshot  # noqa: PLC0415
        state_snapshot = await snapshot()

        new_id = await log_decision(
            decision_type=decision_type,
            title=title,
            reason=parsed.get("reason"),
            outcome=parsed.get("outcome"),
            memory_refs=memory_refs,
            internal_state_snapshot=state_snapshot,
            thread_id=thread_id,
            invocation_id=invocation_id,
            supersedes=supersedes_id,
        )
        if new_id and supersedes_id:
            await mark_superseded(supersedes_id, new_id)
        return new_id
    except Exception:
        logger.exception("decision_log: failed to detect_and_record_decision")
        return None
