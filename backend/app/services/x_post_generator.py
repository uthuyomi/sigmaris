from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.proactive.jwt_manager import get_sigmaris_jwt
from app.services.supabase_rest import (
    _get_client,
    _require_supabase_config,
    get_current_user,
    rest_insert,
)
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


async def get_recent_tracked_posts(*, days: int = 7) -> list[dict[str, Any]]:
    """Phase H-2(docs/sigmaris/phase_h_report.md): tweet_idを持つ(=実際に
    Xへ投稿できたことが確認できている)投稿のみを、新しい順に返す。
    返信検知が「この返信は、シグマリスのどの投稿への返信か」を突き合わ
    せるための、唯一の読み取り口。失敗時は空リスト(既存store関数と
    同じベストエフォート方針)。"""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        r = await client.get(
            f"{base_url}/rest/v1/x_post_history",
            headers=_svc_headers(),
            params={
                "select": "id,text,post_type,tweet_id,posted_at",
                "posted_at": f"gte.{since}",
                "tweet_id": "not.is.null",
                "order": "posted_at.desc",
            },
        )
        if r.is_error:
            logger.warning("x_post_generator: get_recent_tracked_posts HTTP %s", r.status_code)
            return []
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("x_post_generator: get_recent_tracked_posts failed")
        return []


async def record_post(text: str, post_type: str, *, score: float = 0.0, tweet_id: str | None = None) -> None:
    """Save a posted tweet to x_post_history (including quality score).

    tweet_id(Phase H-2で追加): 実際に投稿できた場合のX側のtweet_id。
    LogPublisher使用時(ログのみ)は、疑似ID("log-...")が入る——実際の
    Xの投稿ではないため、返信検知(get_recent_tracked_posts()の対象)は
    これを実データとして扱うが、実際にmentions APIから該当の返信が
    見つかることはない(LogPublisher環境ではXへの接続自体が発生しない
    ため、実害はない)。"""
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.post(
        f"{base_url}/rest/v1/x_post_history",
        headers={**_svc_headers(), "Prefer": "return=minimal"},
        json={"text": text, "post_type": post_type, "post_score": score, "tweet_id": tweet_id},
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
# 【Phase H-1(docs/sigmaris/phase_h_report.md)で新設、旧世代廃止タスク
# (「旧X投稿システムの廃止、及び、新7カテゴリシステムへの実際の接続」)
# で唯一の呼び出し元になった】品質・プライバシーチェック
# (x_content_filter::audit_tweet()・x_privacy_filter::filter_private_
# facts()/filter_private_info())・文字数トリム・名前変換・類似度
# チェックのロジックは、旧5投稿タイプのgenerate_post()(廃止タスクで
# 削除済み)に直書きされていたものを、当時そのまま抜き出しただけであり、
# 削除の過程でも**一切変更していない**——依頼書「既存のx_filterを、
# そのまま、通過させること」への対応を、実際のコード共有によって保証
# する(新しいフィルタの再実装ではない)。


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


# ─── 7カテゴリ(A〜G)の生成エントリポイント ─────────────────────────────────
#
# 【旧世代廃止タスク(docs/sigmaris/phase_h_report.md)での変更点】
# 旧5投稿タイプ(generate_post()・_gather_context()・_build_prompt()・
# should_post_today()・_SLOT_TYPES等)は、本タスクで完全に削除した
# (判断根拠は報告書参照)。本関数は、シグマリスの投稿生成の、唯一の
# エントリポイントになった。**本関数自体は、GeneratedPostを返すのみで、
# 実際にXへ投稿する処理は行わない**——実際の投稿判断・x_publisher.
# post_tweet()の呼び出し・record_post()の呼び出しは、呼び出し元
# (proactive/scheduler.py::_categorized_x_post_check())の責務。


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
