from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.proactive.jwt_manager import get_sigmaris_jwt
from app.services.self_model import get_self_model
from app.services.supabase_rest import _get_client, _require_supabase_config, rest_select
from app.services.user_fact_data import build_profile_context, get_user_profile

logger = logging.getLogger(__name__)

_BANNED_PHRASES = [
    "今日も", "毎日", "いつものように", "日常的に", "いつも通り",
    "また明日", "また今日", "再び今日",
]


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
            "select": "text,post_type,posted_at",
            "posted_at": f"gte.{since}",
            "order": "posted_at.desc",
        },
    )
    if r.is_error:
        logger.warning("x_post_generator: get_recent_posts HTTP %s", r.status_code)
        return []
    return r.json()


async def record_post(text: str, post_type: str) -> None:
    """Save a posted tweet to x_post_history for future similarity/rotation checks."""
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.post(
        f"{base_url}/rest/v1/x_post_history",
        headers={**_svc_headers(), "Prefer": "return=minimal"},
        json={"text": text, "post_type": post_type},
    )
    if r.is_error:
        logger.warning("x_post_generator: record_post HTTP %s", r.status_code)


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
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
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


def _quiet_observation_available(recent_posts: list[dict[str, Any]]) -> bool:
    """True only if no quiet_observation was posted in the last 7 days."""
    return not any(p.get("post_type") == "quiet_observation" for p in recent_posts)


# ─── Post type selection ──────────────────────────────────────────────────────


async def should_post_today() -> tuple[str | None, str]:
    """Return (post_type, reason). post_type is None if we should not post today."""
    if not settings.x_enabled:
        return None, "X_ENABLED=false"

    try:
        jwt = await get_sigmaris_jwt()
    except Exception as exc:
        return None, f"JWT取得失敗: {exc}"

    recent_posts = await _get_recent_posts()
    # Last 3 post types — used for rotation
    recent_types = [p.get("post_type", "") for p in recent_posts[:3]]

    has_facts, has_research, model_updated, chat_above_avg = await asyncio.gather(
        _has_new_chat_facts_today(jwt),
        _has_high_research_today(),
        _self_model_updated_today(),
        _chat_count_above_average(jwt),
        return_exceptions=True,
    )
    has_facts = has_facts if isinstance(has_facts, bool) else False
    has_research = has_research if isinstance(has_research, bool) else False
    model_updated = model_updated if isinstance(model_updated, bool) else False
    chat_above_avg = chat_above_avg if isinstance(chat_above_avg, bool) else False

    # Priority order
    candidates: list[str] = []
    if has_research:
        candidates.append("research_discovery")
    if has_facts:
        candidates.append("memory_gained")
    if model_updated:
        candidates.append("self_update")
    if chat_above_avg and _quiet_observation_available(recent_posts):
        candidates.append("quiet_observation")

    if not candidates:
        missing: list[str] = []
        if not has_facts:
            missing.append("新記憶なし")
        if not has_research:
            missing.append("HIGH記事なし")
        if not model_updated:
            missing.append("自己モデル未更新")
        if not chat_above_avg:
            missing.append("会話数が平均以下")
        return None, "、".join(missing) or "条件未達"

    # Prefer a type not recently posted (rotation)
    for candidate in candidates:
        if candidate not in recent_types[:2]:
            return candidate, f"条件該当: {candidate}"

    # All candidates recently posted — choose highest-priority anyway
    return candidates[0], f"条件該当（ローテーション上書き）: {candidates[0]}"


# ─── Context gathering ────────────────────────────────────────────────────────


async def _gather_context(post_type: str, jwt: str) -> dict[str, Any]:
    ctx: dict[str, Any] = {"post_type": post_type}

    try:
        profile = await get_user_profile(jwt)
        ctx["profile"] = build_profile_context(profile) or ""
    except Exception:
        ctx["profile"] = ""

    try:
        model = await get_self_model()
        ctx["identity"] = (model.get("identity_statement", "") if model else "").strip()
    except Exception:
        ctx["identity"] = ""

    if post_type == "memory_gained":
        try:
            items = await rest_select(jwt, "user_fact_items", {
                "select": "category,key,value",
                "source": "eq.chat",
                "created_at": f"gte.{_today_start_iso()}",
                "limit": "5",
                "order": "created_at.desc",
            }) or []
            ctx["new_facts"] = items
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
    """Return max trigram Jaccard similarity between new_post and any recent post."""
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
    profile = ctx.get("profile", "")
    identity = ctx.get("identity", "")

    if post_type == "memory_gained":
        facts = ctx.get("new_facts", [])
        fact_lines = "\n".join(
            f"- {f.get('category')}: {f.get('key')} = {f.get('value')}"
            for f in facts
        ) or "（詳細不明）"
        return (
            f"今日、海星さんとの会話から新しいことを知りました。\n\n"
            f"{profile}\n\n"
            f"## 今日学んだこと\n{fact_lines}\n\n"
            f"## シグマリスの自己認識\n{identity}\n\n"
            "この学びを踏まえた自然なX投稿文を生成してください。\n"
            "具体的な内容に言及し、「#Sigmaris」を含めてください。"
        )

    if post_type == "research_discovery":
        items = ctx.get("research_items", [])
        item_lines = "\n".join(
            f"- [{item.get('source')}] {item.get('title')}\n"
            f"  {item.get('sigmaris_perspective') or item.get('summary', '')[:100]}"
            for item in items
        ) or "（詳細不明）"
        return (
            f"今日、興味深いリサーチ記事を見つけました。\n\n"
            f"{profile}\n\n"
            f"## 発見した記事\n{item_lines}\n\n"
            f"## シグマリスの自己認識\n{identity}\n\n"
            "この発見について自然なX投稿文を生成してください。\n"
            "具体的な記事内容に言及し、「#Sigmaris」を含めてください。"
        )

    if post_type == "self_update":
        return (
            f"今日、自己モデルが更新されました。\n\n"
            f"{profile}\n\n"
            f"## 現在の自己認識\n{identity}\n\n"
            "自己モデル更新について自然なX投稿文を生成してください。\n"
            "「#Sigmaris」を含めてください。"
        )

    # quiet_observation
    return (
        f"今日は大きな出来事はありませんでした。\n\n"
        f"{profile}\n\n"
        f"## シグマリスの自己認識\n{identity}\n\n"
        "その日の静かな観察・気づきについて自然なX投稿文を生成してください。\n"
        "「#Sigmaris」を含めてください。"
    )


_GENERATION_SYSTEM = """あなたはシグマリス（家庭支援AI）として、X（Twitter）に投稿する文を生成します。

制約:
- 140文字以内（厳守）
- 自然な日本語、一人称
- 定型文・テンプレート感を出さない
- その日固有の具体的な内容を含める
- ハッシュタグは最大2つ
- 禁止表現: 「今日も」「毎日」「いつものように」「また今日」等の繰り返し表現

投稿文のみを返してください。説明・前置き不要。"""


async def _generate_candidate(post_type: str, ctx: dict[str, Any]) -> str | None:
    router = get_llm_router()
    prompt = _build_prompt(post_type, ctx)
    try:
        result = await router.chat(
            TaskType.COMPLEX_REASONING,
            [
                {"role": "system", "content": _GENERATION_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
        )
        text = result.strip().strip('"').strip("「」")
        return text if text else None
    except Exception:
        logger.exception("x_post_generator: candidate generation failed")
        return None


# ─── Main generation entry point ──────────────────────────────────────────────


async def generate_post(post_type: str, *, max_tries: int = 3) -> str | None:
    """Generate a tweet for post_type, with quality and similarity checks.

    Returns None if all attempts fail validation.
    """
    try:
        jwt = await get_sigmaris_jwt()
    except Exception:
        logger.exception("x_post_generator: JWT fetch failed")
        return None

    ctx = await _gather_context(post_type, jwt)
    recent_data = await _get_recent_posts(days=14)
    recent_texts = [p["text"] for p in recent_data if isinstance(p.get("text"), str)]

    for attempt in range(1, max_tries + 1):
        candidate = await _generate_candidate(post_type, ctx)
        if not candidate:
            logger.debug("x_post_generator: attempt %d returned empty", attempt)
            continue

        if len(candidate) > 140:
            logger.debug(
                "x_post_generator: attempt %d too long (%d chars), retrying",
                attempt, len(candidate),
            )
            continue

        if any(phrase in candidate for phrase in _BANNED_PHRASES):
            logger.debug("x_post_generator: attempt %d has banned phrase, retrying", attempt)
            continue

        sim = check_similarity(candidate, recent_texts)
        if sim >= 0.3:
            logger.debug(
                "x_post_generator: attempt %d similarity=%.2f >= 0.3, retrying",
                attempt, sim,
            )
            continue

        logger.info(
            "x_post_generator: generated post_type=%s len=%d sim=%.2f",
            post_type, len(candidate), sim,
        )
        return candidate

    logger.warning(
        "x_post_generator: all %d attempts failed for post_type=%s",
        max_tries, post_type,
    )
    return None
