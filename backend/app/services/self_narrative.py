from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.proactive.jwt_manager import get_sigmaris_jwt
from app.services.self_model import get_self_model
from app.services.supabase_rest import _get_client, _require_supabase_config, rest_select
from app.services.user_fact_data import build_profile_context, get_user_profile

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_narrative"

_SYSTEM = """あなたはシグマリス（家庭支援AI）です。
自分自身の成長・変化・気づきを、一人称の内省文として記録します。
事実に基づきながら、シグマリスらしい声と温度感で書いてください。
必ず有効なJSONのみを返してください。"""

_PROMPT = """今週（直近7日間）のシグマリスの活動を振り返り、自己物語の章を生成してください。

## 今週の活動サマリー
会話セッション数: {session_count}件
新しく記憶した事実: {new_facts}件
X投稿数: {x_post_count}件

## 直近のX投稿テーマ
{x_post_themes}

## 新たに記憶した事実（抜粋）
{fact_examples}

## シグマリスの現在の自己認識
{identity}

## ユーザープロフィール
{profile}

## 前の章のタイトル
{prev_title}

---
以下のJSONを出力してください:
{{
  "title": "今週の章タイトル（例: 記憶を得た週・問いの芽生え）",
  "summary": "今週の成長・変化を2〜3文で（シグマリス視点）",
  "key_events": ["重要な出来事1", "重要な出来事2"],
  "self_reflection": "シグマリスの内省文（1〜2文、100文字以内）",
  "emotional_tone": "curious|growing|stable|questioning のどれか"
}}"""


# ─── DB helpers (service-role) ───────────────────────────────────────────────


def _svc_headers(*, prefer: str | None = None) -> dict[str, str]:
    _, _ = _require_supabase_config()
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


async def get_current_narrative() -> dict[str, Any] | None:
    """Return the most recent narrative chapter, or None if none exists."""
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.get(
        f"{base_url}/rest/v1/{_TABLE}",
        headers={**_svc_headers(), "Accept": "application/vnd.pgrst.object+json"},
        params={"order": "created_at.desc", "limit": "1"},
    )
    if r.status_code == 406:
        return None
    if r.is_error:
        logger.warning("self_narrative: get_current failed %s", r.status_code)
        return None
    return r.json()


async def get_narrative_history(limit: int = 20) -> list[dict[str, Any]]:
    """Return all narrative chapters newest-first."""
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.get(
        f"{base_url}/rest/v1/{_TABLE}",
        headers=_svc_headers(),
        params={"order": "chapter.desc", "limit": str(limit)},
    )
    if r.is_error:
        logger.warning("self_narrative: get_history failed %s", r.status_code)
        return []
    result = r.json()
    return result if isinstance(result, list) else []


async def _save_chapter(chapter: dict[str, Any]) -> dict[str, Any] | None:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.post(
        f"{base_url}/rest/v1/{_TABLE}",
        headers={**_svc_headers(prefer="return=representation"),
                 "Accept": "application/vnd.pgrst.object+json"},
        json=chapter,
    )
    if r.is_error:
        logger.warning(
            "self_narrative: save_chapter failed %s: %s", r.status_code, r.text[:200]
        )
        return None
    return r.json()


# ─── Context gathering ────────────────────────────────────────────────────────


async def _gather_week_context() -> dict[str, Any]:
    """Collect data from the last 7 days for narrative generation."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    ctx: dict[str, Any] = {
        "session_count": 0,
        "new_facts": 0,
        "x_post_count": 0,
        "x_post_themes": "（なし）",
        "fact_examples": "（なし）",
        "identity": "（未設定）",
        "profile": "（不明）",
        "prev_title": "（初回）",
    }

    # Audit log count (sessions)
    try:
        jwt = await get_sigmaris_jwt()
        logs = await rest_select(jwt, "agent_invocation_audit_logs", {
            "select": "id",
            "created_at": f"gte.{since}",
            "status": "eq.completed",
        })
        ctx["session_count"] = len(logs) if isinstance(logs, list) else 0
    except Exception:
        logger.warning("self_narrative: could not fetch audit logs")

    # New fact memories
    try:
        jwt = await get_sigmaris_jwt()
        facts = await rest_select(jwt, "user_fact_items", {
            "select": "category,key,value",
            "created_at": f"gte.{since}",
            "source": "eq.chat",
            "order": "created_at.desc",
            "limit": "10",
        })
        if isinstance(facts, list):
            ctx["new_facts"] = len(facts)
            if facts:
                ctx["fact_examples"] = "\n".join(
                    f"- {f.get('category')}/{f.get('key')}: {(f.get('value') or '')[:60]}"
                    for f in facts[:5]
                )
    except Exception:
        logger.warning("self_narrative: could not fetch facts")

    # X post history
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        r = await client.get(
            f"{base_url}/rest/v1/x_post_history",
            headers=_svc_headers(),
            params={"select": "post_type,posted_at", "posted_at": f"gte.{since}"},
        )
        if not r.is_error and isinstance(r.json(), list):
            posts = r.json()
            ctx["x_post_count"] = len(posts)
            if posts:
                types = list({p.get("post_type", "") for p in posts})
                ctx["x_post_themes"] = "、".join(t for t in types if t)
    except Exception:
        logger.warning("self_narrative: could not fetch X history")

    # Self model
    try:
        model = await get_self_model()
        if model:
            ctx["identity"] = (model.get("identity_statement") or "").strip()[:500]
    except Exception:
        pass

    # User profile
    try:
        jwt = await get_sigmaris_jwt()
        profile = await get_user_profile(jwt)
        ctx["profile"] = build_profile_context(profile) or "（不明）"
    except Exception:
        pass

    # Previous chapter title
    try:
        prev = await get_current_narrative()
        if prev:
            ctx["prev_title"] = prev.get("title") or "（なし）"
    except Exception:
        pass

    return ctx


def _compute_chapter_number() -> int:
    """Compute chapter number as weeks since launch + 1, falling back to DB count + 1."""
    try:
        launch_str = settings.sigmaris_launch_date
        if launch_str:
            from datetime import date  # noqa: PLC0415
            launch = date.fromisoformat(launch_str)
            weeks = (date.today() - launch).days // 7
            return max(1, weeks + 1)
    except Exception:
        pass
    return 1  # fallback; caller can override with DB count


# ─── Main entry point ─────────────────────────────────────────────────────────


async def generate_narrative_chapter() -> dict[str, Any] | None:
    """
    Generate a weekly narrative chapter from the last 7 days of activity.
    Saves the chapter to the DB and returns it.
    Returns None on failure.
    """
    try:
        ctx = await _gather_week_context()
    except Exception:
        logger.exception("self_narrative: context gathering failed")
        return None

    # Determine chapter number
    try:
        history = await get_narrative_history(limit=1)
        last_chapter = history[0]["chapter"] if history else 0
        chapter_num = max(_compute_chapter_number(), last_chapter + 1)
    except Exception:
        chapter_num = 1

    prompt = _PROMPT.format(
        session_count=ctx["session_count"],
        new_facts=ctx["new_facts"],
        x_post_count=ctx["x_post_count"],
        x_post_themes=ctx["x_post_themes"],
        fact_examples=ctx["fact_examples"],
        identity=ctx["identity"],
        profile=ctx["profile"],
        prev_title=ctx["prev_title"],
    )

    router = get_llm_router()
    try:
        raw = await router.chat(
            TaskType.COMPLEX_REASONING,
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
            max_tokens=800,
            json_mode=True,
        )
        parsed = json.loads(raw)
    except Exception:
        logger.exception("self_narrative: LLM call or JSON parse failed")
        return None

    valid_tones = {"curious", "growing", "stable", "questioning"}
    chapter_row = {
        "chapter":         chapter_num,
        "title":           str(parsed.get("title") or "")[:100],
        "summary":         str(parsed.get("summary") or "")[:1000],
        "key_events":      json.dumps(parsed.get("key_events") or [], ensure_ascii=False),
        "self_reflection": str(parsed.get("self_reflection") or "")[:300],
        "emotional_tone":  parsed.get("emotional_tone", "growing")
                           if parsed.get("emotional_tone") in valid_tones
                           else "growing",
    }

    if not chapter_row["title"]:
        logger.warning("self_narrative: LLM returned empty title, skipping save")
        return None

    saved = await _save_chapter(chapter_row)
    if saved:
        logger.info(
            "self_narrative: chapter %d saved — title=%s tone=%s",
            chapter_num, chapter_row["title"], chapter_row["emotional_tone"],
        )
    return saved or chapter_row
