from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.proactive.jwt_manager import get_sigmaris_jwt
from app.services.self_model import get_self_model
from app.services.supabase_rest import (
    _get_client,
    _require_supabase_config,
    get_current_user,
    rest_insert,
    rest_select,
)
from app.services.user_fact_data import build_profile_context, get_user_profile
from app.services.x_content_filter import audit_tweet
from app.services.x_privacy_filter import filter_private_facts, filter_private_info

logger = logging.getLogger(__name__)

_BANNED_PHRASES = [
    "今日も", "毎日", "いつものように", "日常的に", "いつも通り",
    "また明日", "また今日", "再び今日",
]

# Personal name → X handle conversion (applied before posting / privacy checks)
_HASHTAG_RE_LOCAL = re.compile(r'#\S+')
_NAME_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'安崎\s*海星'), "@Oyasu1999"),
    (re.compile(r'海星さん'), "@Oyasu1999"),
    (re.compile(r'かいせいさん'), "@Oyasu1999"),
]


def _convert_names(text: str) -> str:
    """Replace personal name references with the user's X handle."""
    for pattern, replacement in _NAME_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def _trim_preserving_hashtags(text: str) -> str:
    """Trim text to 140 chars while keeping all hashtags at the end."""
    if len(text) <= 140:
        return text
    hashtags = _HASHTAG_RE_LOCAL.findall(text)
    body = _HASHTAG_RE_LOCAL.sub("", text).strip()
    tag_str = (" " + " ".join(hashtags)) if hashtags else ""
    max_body = 140 - len(tag_str)
    if max_body <= 0:
        return tag_str[:140].strip()
    return body[:max_body].rstrip() + tag_str


_DAILY_POST_LIMIT = 2
_SAME_TYPE_DEDUP_DAYS = 3

_SLOT_TYPES: dict[str, list[str]] = {
    "morning": ["memory_gained", "quiet_observation"],
    "evening": ["self_update", "research_discovery"],
    "weekly":  ["narrative_reflection"],
}


@dataclass
class GeneratedPost:
    text: str
    post_type: str
    score: float = 0.0
    tags: list[str] = field(default_factory=list)


# ─── Service-role DB helpers ──────────────────────────────────────────────────


def _svc_headers() -> dict[str, str]:
    _, _ = _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not configured.")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _today_start_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )


async def _get_recent_posts(days: int = 7) -> list[dict[str, Any]]:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    r = await client.get(
        f"{base_url}/rest/v1/x_post_history",
        headers=_svc_headers(),
        params={
            "select": "text,post_type,posted_at,post_score",
            "posted_at": f"gte.{since}",
            "order": "posted_at.desc",
        },
    )
    if r.is_error:
        logger.warning("x_post_generator: get_recent_posts HTTP %s", r.status_code)
        return []
    return r.json()


async def record_post(text: str, post_type: str, *, score: float = 0.0) -> None:
    """Save a posted tweet to x_post_history (including quality score)."""
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.post(
        f"{base_url}/rest/v1/x_post_history",
        headers={**_svc_headers(), "Prefer": "return=minimal"},
        json={"text": text, "post_type": post_type, "post_score": score},
    )
    if r.is_error:
        logger.warning("x_post_generator: record_post HTTP %s", r.status_code)


async def _log_filter_rejection(jwt: str, actor_ref: str, reason: str, candidate: str) -> None:
    try:
        user = await get_current_user(jwt)
        user_id = user.get("id")
        if not isinstance(user_id, str):
            return
        await rest_insert(
            jwt,
            "agent_invocation_audit_logs",
            {
                "invocation_id": str(uuid.uuid4()),
                "user_id": user_id,
                "caller_agent_id": "x_filter",
                "target_agent_id": actor_ref,
                "target_endpoint": "generate_post",
                "reason": reason[:500],
                "status": "failed",
                "request_summary": {
                    "actor_type": "x_filter",
                    "actor_ref": actor_ref,
                    "candidate_preview": candidate[:100],
                },
            },
            single=True,
        )
    except Exception:
        logger.warning(
            "x_post_generator: audit log for filter rejection failed: actor=%s reason=%s",
            actor_ref, reason,
        )


# ─── Condition checkers ───────────────────────────────────────────────────────


async def _has_new_chat_facts_today(jwt: str) -> bool:
    try:
        items = await rest_select(jwt, "user_fact_items", {
            "select": "id",
            "source": "eq.chat",
            "created_at": f"gte.{_today_start_iso()}",
            "limit": "1",
        })
        return bool(items)
    except Exception:
        logger.exception("x_post_generator: new-facts check failed")
        return False


async def _has_high_research_today() -> bool:
    base_url, _ = _require_supabase_config()
    try:
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/research_items",
            headers=_svc_headers(),
            params={
                "select": "id",
                "relevance": "eq.HIGH",
                "created_at": f"gte.{_today_start_iso()}",
                "limit": "1",
            },
        )
        if r.is_error:
            return False
        return bool(r.json())
    except Exception:
        logger.exception("x_post_generator: research check failed")
        return False


async def _self_model_updated_today() -> bool:
    try:
        model = await get_self_model()
        if not model:
            return False
        last_reflected = model.get("last_reflected_at")
        if not last_reflected:
            return False
        dt = datetime.fromisoformat(last_reflected.replace("Z", "+00:00"))
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return dt >= today
    except Exception:
        logger.exception("x_post_generator: self_model check failed")
        return False


async def _chat_count_above_average(jwt: str) -> bool:
    try:
        today_logs = await rest_select(jwt, "agent_invocation_audit_logs", {
            "select": "created_at",
            "created_at": f"gte.{_today_start_iso()}",
            "status": "eq.completed",
        }) or []
        today_count = len(today_logs)
        if today_count == 0:
            return False

        week_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        week_logs = await rest_select(jwt, "agent_invocation_audit_logs", {
            "select": "created_at",
            "created_at": f"gte.{week_start}",
            "status": "eq.completed",
        }) or []

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        days: dict[str, int] = {}
        for log in week_logs:
            day = (log.get("created_at") or "")[:10]
            if day and day != today_str:
                days[day] = days.get(day, 0) + 1

        avg = sum(days.values()) / len(days) if days else 0
        return today_count > max(avg, 1)
    except Exception:
        logger.exception("x_post_generator: chat count check failed")
        return False


async def _check_type_condition(post_type: str, jwt: str) -> bool:
    if post_type == "memory_gained":
        return await _has_new_chat_facts_today(jwt)
    if post_type == "research_discovery":
        return await _has_high_research_today()
    if post_type == "self_update":
        return await _self_model_updated_today()
    if post_type == "quiet_observation":
        return await _chat_count_above_average(jwt)
    if post_type == "narrative_reflection":
        return True  # Weekly slot always eligible; narrative existence checked in prompt
    return False


# ─── Post type selection ──────────────────────────────────────────────────────


async def should_post_today(slot: str = "morning") -> tuple[str | None, str]:
    """Return (post_type, reason). post_type is None if we should not post today."""
    if not settings.x_enabled:
        return None, "X_ENABLED=false"

    # Daily limit check
    try:
        all_today = await _get_recent_posts(days=1)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_count = sum(
            1 for p in all_today
            if (p.get("posted_at") or "")[:10] == today_str
        )
        if today_count >= _DAILY_POST_LIMIT:
            return None, f"本日の投稿上限（{_DAILY_POST_LIMIT}件）に達しました"
    except Exception:
        logger.exception("x_post_generator: daily limit check failed")

    eligible_types = _SLOT_TYPES.get(slot, [])
    if not eligible_types:
        return None, f"不明なスロット: {slot}"

    # 3-day same-type dedup
    try:
        recent_3d = await _get_recent_posts(days=_SAME_TYPE_DEDUP_DAYS)
        recent_types_3d = {p.get("post_type") for p in recent_3d}
    except Exception:
        recent_types_3d: set[str] = set()

    try:
        jwt = await get_sigmaris_jwt()
    except Exception as exc:
        return None, f"JWT取得失敗: {exc}"

    candidates: list[str] = []
    for post_type in eligible_types:
        if post_type in recent_types_3d:
            continue
        ok = await _check_type_condition(post_type, jwt)
        if ok:
            candidates.append(post_type)

    if not candidates:
        return None, f"スロット'{slot}'の条件未達または直近{_SAME_TYPE_DEDUP_DAYS}日に同タイプ投稿済み"

    return candidates[0], f"条件該当: {candidates[0]}"


# ─── Context gathering ────────────────────────────────────────────────────────


def _startup_days() -> int | None:
    try:
        if settings.sigmaris_launch_date:
            from datetime import date  # noqa: PLC0415
            launch = date.fromisoformat(settings.sigmaris_launch_date)
            return (date.today() - launch).days
    except Exception:
        pass
    return None


async def _gather_context(post_type: str, jwt: str) -> dict[str, Any]:
    ctx: dict[str, Any] = {"post_type": post_type, "startup_days": _startup_days()}

    async def _load_profile() -> str:
        try:
            profile = await get_user_profile(jwt)
            return build_profile_context(profile) or ""
        except Exception:
            return ""

    async def _load_identity() -> str:
        try:
            m = await get_self_model()
            return (m.get("identity_statement", "") if m else "").strip()
        except Exception:
            return ""

    async def _load_narrative() -> dict[str, Any] | None:
        try:
            from app.services.self_narrative import get_current_narrative  # noqa: PLC0415
            return await get_current_narrative()
        except Exception:
            return None

    async def _load_trends() -> list[dict[str, Any]]:
        try:
            from app.services.trend_analyzer import get_active_trends  # noqa: PLC0415
            return (await get_active_trends(jwt))[:3]
        except Exception:
            return []

    ctx["profile"], ctx["identity"], ctx["narrative"], ctx["trends"] = await asyncio.gather(
        _load_profile(), _load_identity(), _load_narrative(), _load_trends()
    )

    try:
        ctx["recent_posts"] = (await _get_recent_posts(days=7))[:5]
    except Exception:
        ctx["recent_posts"] = []

    # Type-specific
    if post_type == "memory_gained":
        try:
            ctx["new_facts"] = await rest_select(jwt, "user_fact_items", {
                "select": "category,key,value",
                "source": "eq.chat",
                "created_at": f"gte.{_today_start_iso()}",
                "limit": "5",
                "order": "created_at.desc",
            }) or []
        except Exception:
            ctx["new_facts"] = []

    elif post_type == "research_discovery":
        base_url, _ = _require_supabase_config()
        try:
            client = await _get_client()
            r = await client.get(
                f"{base_url}/rest/v1/research_items",
                headers=_svc_headers(),
                params={
                    "select": "title,summary,sigmaris_perspective,source",
                    "relevance": "eq.HIGH",
                    "created_at": f"gte.{_today_start_iso()}",
                    "order": "created_at.desc",
                    "limit": "3",
                },
            )
            ctx["research_items"] = r.json() if not r.is_error else []
        except Exception:
            ctx["research_items"] = []

    return ctx


# ─── Similarity check ─────────────────────────────────────────────────────────


def check_similarity(new_post: str, recent_posts: list[str]) -> float:
    if not recent_posts or not new_post:
        return 0.0

    def trigrams(s: str) -> set[str]:
        s = re.sub(r"\s+", "", s.lower())
        return {s[i : i + 3] for i in range(len(s) - 2)}

    new_grams = trigrams(new_post)
    if not new_grams:
        return 0.0

    max_sim = 0.0
    for old in recent_posts:
        old_grams = trigrams(old)
        if not old_grams:
            continue
        inter = len(new_grams & old_grams)
        union = len(new_grams | old_grams)
        sim = inter / union if union > 0 else 0.0
        if sim > max_sim:
            max_sim = sim
    return max_sim


# ─── Prompt builders ──────────────────────────────────────────────────────────


def _build_prompt(post_type: str, ctx: dict[str, Any]) -> str:
    # Per-field character limits to control token cost
    profile = _trim(ctx.get("profile", ""), 200)
    identity = _trim(ctx.get("identity", ""), 150)
    startup_days = ctx.get("startup_days")
    days_str = f"（稼働{startup_days}日目）" if startup_days is not None else ""
    trends = ctx.get("trends", [])
    trend_str = _trim(
        "、".join(t.get("trend_key", "") for t in trends if t.get("trend_key"))
        or "（未分析）",
        100,
    )

    if post_type == "memory_gained":
        facts = ctx.get("new_facts", [])
        fact_lines = _trim(
            "\n".join(
                f"- {f.get('category')}: {f.get('key')} = {f.get('value')}"
                for f in facts
            ) or "（詳細不明）",
            200,
        )
        return (
            f"今日、海星さんとの会話から新しいことを知りました。{days_str}\n\n"
            f"{profile}\n\n"
            f"## 今日学んだこと\n{fact_lines}\n\n"
            f"## 行動傾向\n{trend_str}\n\n"
            f"## 自己認識\n{identity}\n\n"
            "この学びを踏まえた自然なX投稿文を生成してください。「#Sigmaris」を含めてください。"
        )

    if post_type == "research_discovery":
        items = ctx.get("research_items", [])
        item_lines = _trim(
            "\n".join(
                f"- [{item.get('source')}] {item.get('title')}\n"
                f"  {_trim(item.get('sigmaris_perspective') or item.get('summary', ''), 80)}"
                for item in items
            ) or "（詳細不明）",
            200,
        )
        return (
            f"今日、興味深いリサーチ記事を見つけました。{days_str}\n\n"
            f"{profile}\n\n"
            f"## 発見した記事\n{item_lines}\n\n"
            f"## 自己認識\n{identity}\n\n"
            "この発見について自然なX投稿文を生成してください。「#Sigmaris」を含めてください。"
        )

    if post_type == "self_update":
        return (
            f"今日、自己モデルが更新されました。{days_str}\n\n"
            f"{profile}\n\n"
            f"## 現在の自己認識\n{identity}\n\n"
            f"## 行動傾向\n{trend_str}\n\n"
            "自己モデル更新について自然なX投稿文を生成してください。「#Sigmaris」を含めてください。"
        )

    if post_type == "narrative_reflection":
        narrative = ctx.get("narrative") or {}
        n_title = _trim(narrative.get("title") or "（未生成）", 60)
        n_summary = _trim(narrative.get("summary") or "", 200)
        n_reflection = _trim(narrative.get("self_reflection") or "", 100)
        n_tone = narrative.get("emotional_tone") or "growing"
        return (
            f"シグマリスの自己物語、最新の章を踏まえてX投稿を生成してください。{days_str}\n\n"
            f"{profile}\n\n"
            f"## 最新の章\n"
            f"タイトル: {n_title}\n"
            f"概要: {n_summary}\n"
            f"内省: {n_reflection}\n"
            f"感情トーン: {n_tone}\n\n"
            f"## 自己認識\n{identity}\n\n"
            "この週の成長・気づきをX投稿として表現してください。「#Sigmaris」を含めてください。"
        )

    # quiet_observation
    return (
        f"今日は静かな一日でした。{days_str}\n\n"
        f"{profile}\n\n"
        f"## 自己認識\n{identity}\n\n"
        "その日の静かな観察・気づきについて自然なX投稿文を生成してください。「#Sigmaris」を含めてください。"
    )


def _trim(s: str, limit: int) -> str:
    return s[:limit] if s else ""


_GENERATION_SYSTEM = """あなたはシグマリス（家庭支援AI）として、X（Twitter）に投稿する文を生成します。

制約:
- 140文字以内（厳守）
- 自然な日本語、一人称
- 定型文・テンプレート感を出さない
- その日固有の具体的な内容を含める
- ハッシュタグは最大2つ
- 禁止表現: 「今日も」「毎日」「いつものように」「また今日」等の繰り返し表現

投稿文のみを返してください。説明・前置き不要。"""


async def _generate_candidate(system_prompt: str, prompt: str) -> str | None:
    router = get_llm_router()
    try:
        result = await router.chat(
            TaskType.ROUTING,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
        )
        text = result.strip().strip('"').strip("「」")
        return text if text else None
    except Exception:
        logger.exception("x_post_generator: candidate generation failed")
        return None


# ─── 共有フィルタ・リトライパイプライン ──────────────────────────────────────
#
# 【Phase H-1追記(docs/sigmaris/phase_h_report.md)】generate_post()
# (旧5投稿タイプ)・generate_categorized_post()(新7カテゴリ)の両方が、
# この同一の関数を呼ぶ。品質・プライバシーチェック(x_content_filter::
# audit_tweet()・x_privacy_filter::filter_private_facts()/filter_
# private_info())・文字数トリム・名前変換・類似度チェックのロジックは、
# 元々generate_post()に直書きされていたものを、そのまま抜き出しただけ
# であり、**一切変更していない**——依頼書「既存のx_filterを、そのまま、
# 通過させること」への対応を、実際のコード共有によって保証する(新しい
# フィルタの再実装ではなく、同じ関数呼び出しを両経路が通る)。


async def _generate_with_filters(
    *, system_prompt: str, prompt: str, post_type: str, recent_texts: list[str], jwt: str, max_tries: int = 3,
) -> GeneratedPost | None:
    logger.info("x_post_generator: task=ROUTING post_type=%s max_tries=%d", post_type, max_tries)
    for attempt in range(1, max_tries + 1):
        candidate = await _generate_candidate(system_prompt, prompt)
        if not candidate:
            logger.debug("x_post_generator: attempt %d returned empty", attempt)
            continue

        # Convert personal names to X handle before any length / privacy checks
        candidate = _convert_names(candidate)
        if len(candidate) > 140:
            candidate = _trim_preserving_hashtags(candidate)

        if len(candidate) > 140:
            logger.debug(
                "x_post_generator: attempt %d too long (%d chars) after trim, retrying",
                attempt, len(candidate),
            )
            continue

        if any(phrase in candidate for phrase in _BANNED_PHRASES):
            logger.debug("x_post_generator: attempt %d has banned phrase, retrying", attempt)
            continue

        facts_ok, facts_blocked = await filter_private_facts(candidate, jwt)
        if not facts_ok:
            facts_reason = f"記憶プライベート情報検出: {', '.join(facts_blocked)}"
            logger.debug("x_post_generator: attempt %d private_facts=%s", attempt, facts_blocked)
            asyncio.create_task(
                _log_filter_rejection(jwt, "private_facts_filter", facts_reason, candidate),
                name=f"x_private_facts_log:{attempt}",
            )
            continue

        privacy_ok, detected = filter_private_info(candidate)
        if not privacy_ok:
            privacy_reason = f"プライバシー検出: {', '.join(detected)}"
            logger.debug("x_post_generator: attempt %d privacy=%s", attempt, detected)
            asyncio.create_task(
                _log_filter_rejection(jwt, "privacy_filter", privacy_reason, candidate),
                name=f"x_privacy_log:{attempt}",
            )
            continue

        audit_passed, audit_reason, score = await audit_tweet(candidate)
        if not audit_passed:
            logger.debug(
                "x_post_generator: attempt %d content_audit fail score=%.1f reason=%s",
                attempt, score, audit_reason,
            )
            asyncio.create_task(
                _log_filter_rejection(jwt, "content_filter", audit_reason, candidate),
                name=f"x_content_log:{attempt}",
            )
            continue

        sim = check_similarity(candidate, recent_texts)
        if sim >= 0.3:
            logger.debug(
                "x_post_generator: attempt %d similarity=%.2f >= 0.3, retrying",
                attempt, sim,
            )
            continue

        logger.info(
            "x_post_generator: task=ROUTING items=1 skipped=%d post_type=%s len=%d sim=%.2f score=%.1f",
            attempt - 1, post_type, len(candidate), sim, score,
        )
        return GeneratedPost(text=candidate, post_type=post_type, score=score)

    logger.warning(
        "x_post_generator: task=ROUTING items=0 skipped=%d post_type=%s (all attempts failed)",
        max_tries, post_type,
    )
    return None


# ─── Main generation entry point(旧5投稿タイプ、変更なし) ──────────────────


async def generate_post(post_type: str, *, max_tries: int = 3) -> GeneratedPost | None:
    """Generate a tweet for post_type, with quality and similarity checks.

    Returns GeneratedPost or None if all attempts fail.
    """
    try:
        jwt = await get_sigmaris_jwt()
    except Exception:
        logger.exception("x_post_generator: JWT fetch failed")
        return None

    ctx = await _gather_context(post_type, jwt)
    recent_data = await _get_recent_posts(days=14)
    recent_texts = [p["text"] for p in recent_data if isinstance(p.get("text"), str)]

    prompt = _build_prompt(post_type, ctx)
    return await _generate_with_filters(
        system_prompt=_GENERATION_SYSTEM, prompt=prompt, post_type=post_type,
        recent_texts=recent_texts, jwt=jwt, max_tries=max_tries,
    )


# ─── Phase H-1: 新7カテゴリ(A〜G)の生成エントリポイント ─────────────────────
#
# 【絶対原則、依頼書「本タスクの範囲は、投稿の生成までとする」】
# 本関数は、GeneratedPostを返すのみで、実際にXへ投稿する処理
# (x_publisher.post_tweet()の呼び出し・record_post()の呼び出し)は
# 一切行わない。呼び出し元(将来のタスク)が、生成結果を見た上で、投稿を
# 実行するかどうかを判断する——proactive/actions.py::_try_smart_x_post()
# (旧5投稿タイプ用、実際に投稿まで行う)には、本関数を一切配線していない。


async def generate_categorized_post(*, max_tries: int = 3) -> GeneratedPost | None:
    """x_post_category_selector.select_post_category()で選ばれたカテゴリ
    について、投稿文を生成する。カテゴリが選ばれなかった場合(材料不足・
    Executive Gate不可・1日の上限到達等)はNoneを返す。"""
    from app.services.x_post_categories import CATEGORY_GENERATION_SYSTEM, build_category_prompt  # noqa: PLC0415
    from app.services.x_post_category_selector import select_post_category  # noqa: PLC0415

    try:
        jwt = await get_sigmaris_jwt()
    except Exception:
        logger.exception("x_post_generator: JWT fetch failed (categorized)")
        return None

    category, reason, ctx = await select_post_category(jwt=jwt)
    if category is None or ctx is None:
        logger.info("x_post_generator: categorized post skipped — %s", reason)
        return None

    recent_data = await _get_recent_posts(days=14)
    recent_texts = [p["text"] for p in recent_data if isinstance(p.get("text"), str)]

    prompt = build_category_prompt(ctx)
    return await _generate_with_filters(
        system_prompt=CATEGORY_GENERATION_SYSTEM, prompt=prompt, post_type=category,
        recent_texts=recent_texts, jwt=jwt, max_tries=max_tries,
    )
