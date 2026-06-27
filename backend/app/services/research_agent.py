from __future__ import annotations

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.services.local_llm import TaskType, get_llm_router
from app.services.proactive.jwt_manager import get_sigmaris_jwt
from app.services.self_model import get_self_model
from app.services.supabase_rest import _get_client, _require_supabase_config
from app.services.user_fact_data import build_profile_context, get_user_profile

logger = logging.getLogger(__name__)

_ARXIV_URL = "https://export.arxiv.org/api/query"
_ARXIV_ATOM_NS = "http://www.w3.org/2005/Atom"
_GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
_NEWSAPI_URL = "https://newsapi.org/v2/everything"
_HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
_HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"
_REDDIT_FEEDS = [
    ("https://www.reddit.com/r/MachineLearning/.rss", "reddit_ml"),
    ("https://www.reddit.com/r/robotics/.rss", "reddit_robotics"),
    ("https://www.reddit.com/r/artificial/.rss", "reddit_ai"),
]
_SIGMARIS_INTERESTS = (
    "AI・機械学習・LLM、ロボティクス・ドローン、航空・空の世界、"
    "キャンプ・アウトドア、釣り・水辺、個人開発・インディーアプリ"
)


# ─── Service-role DB helpers ──────────────────────────────────────────────────


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


async def _db_insert_item(item: dict[str, Any]) -> dict[str, Any] | None:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.post(
        f"{base_url}/rest/v1/research_items",
        headers={
            **_svc_headers(prefer="return=representation"),
            "Accept": "application/vnd.pgrst.object+json",
        },
        json=item,
    )
    if r.is_error:
        logger.warning("research_agent: DB insert failed %s: %s", r.status_code, r.text[:200])
        return None
    return r.json()


async def _db_update_perspective(item_id: str, perspective: str) -> None:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    r = await client.patch(
        f"{base_url}/rest/v1/research_items",
        headers=_svc_headers(prefer="return=minimal"),
        params={"id": f"eq.{item_id}"},
        json={"sigmaris_perspective": perspective},
    )
    if r.is_error:
        logger.warning("research_agent: perspective update failed %s", r.status_code)


async def _db_get_today_titles() -> list[str]:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    r = await client.get(
        f"{base_url}/rest/v1/research_items",
        headers=_svc_headers(),
        params={"select": "title", "created_at": f"gte.{today_start}"},
    )
    if r.is_error:
        return []
    return [row["title"] for row in r.json() if isinstance(row.get("title"), str)]


_MAX_PERSPECTIVES_PER_DAY = 5


async def _db_count_today_high() -> int:
    """Count HIGH research_items created today (for duplicate-run skip check)."""
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    r = await client.get(
        f"{base_url}/rest/v1/research_items",
        headers=_svc_headers(),
        params={"select": "id", "relevance": "eq.HIGH", "created_at": f"gte.{today_start}"},
    )
    if r.is_error:
        return 0
    data = r.json()
    return len(data) if isinstance(data, list) else 0


async def _db_count_today_perspectives() -> int:
    """Count HIGH items with non-null sigmaris_perspective created today."""
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    r = await client.get(
        f"{base_url}/rest/v1/research_items",
        headers=_svc_headers(),
        params={
            "select": "id",
            "relevance": "eq.HIGH",
            "sigmaris_perspective": "not.is.null",
            "created_at": f"gte.{today_start}",
        },
    )
    if r.is_error:
        return 0
    data = r.json()
    return len(data) if isinstance(data, list) else 0


async def _db_delete_expired() -> None:
    base_url, _ = _require_supabase_config()
    client = await _get_client()
    now = datetime.now(timezone.utc).isoformat()
    r = await client.delete(
        f"{base_url}/rest/v1/research_items",
        headers=_svc_headers(),
        params={"expires_at": f"lt.{now}"},
    )
    if r.is_error:
        logger.warning("research_agent: delete expired failed %s", r.status_code)
    else:
        logger.info("research_agent: expired items cleaned up")


# ─── Source fetchers ──────────────────────────────────────────────────────────


async def _fetch_arxiv_items() -> list[dict[str, str]]:
    params = {
        "search_query": "(cat:cs.AI OR cat:cs.LG OR cat:cs.RO OR cat:q-bio.NC)",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": "20",
        "start": "0",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0)) as client:
            r = await client.get(_ARXIV_URL, params=params)
            r.raise_for_status()
    except Exception:
        logger.exception("research_agent: arXiv fetch failed")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(r.text)
        ns = {"atom": _ARXIV_ATOM_NS}
        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            id_el = entry.find("atom:id", ns)
            published_el = entry.find("atom:published", ns)
            if title_el is None or id_el is None:
                continue
            if published_el is not None and published_el.text:
                try:
                    pub_dt = datetime.fromisoformat(
                        published_el.text.strip().replace("Z", "+00:00")
                    )
                    if pub_dt < cutoff:
                        continue
                except ValueError:
                    pass
            items.append({
                "source": "arxiv",
                "title": (title_el.text or "").strip().replace("\n", " "),
                "url": (id_el.text or "").strip(),
                "raw_summary": (
                    (summary_el.text or "").strip()[:1000]
                    if summary_el is not None else ""
                ),
            })
    except ET.ParseError:
        logger.exception("research_agent: arXiv XML parse failed")

    logger.info("research_agent: arXiv → %d items", len(items))
    return items


async def _fetch_github_items() -> list[dict[str, str]]:
    since = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%d")
    params = {
        "q": (
            f"created:>{since} stars:>20 "
            "(topic:machine-learning OR topic:ai OR topic:llm OR topic:deep-learning)"
        ),
        "sort": "stars",
        "order": "desc",
        "per_page": "10",
    }
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(_GITHUB_SEARCH_URL, params=params, headers=headers)
            r.raise_for_status()
    except Exception:
        logger.exception("research_agent: GitHub fetch failed")
        return []

    items = [
        {
            "source": "github",
            "title": repo.get("full_name", ""),
            "url": repo.get("html_url", ""),
            "raw_summary": (repo.get("description") or "")[:500],
        }
        for repo in r.json().get("items", [])
        if repo.get("full_name") and repo.get("html_url")
    ]
    logger.info("research_agent: GitHub → %d items", len(items))
    return items


async def _fetch_hn_items() -> list[dict[str, str]]:
    """Fetch top HackerNews stories (no API key needed via Firebase API)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(_HN_TOP_STORIES_URL)
            r.raise_for_status()
            story_ids: list[int] = r.json()[:30]
    except Exception:
        logger.exception("research_agent: HN topstories fetch failed")
        return []

    items: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        responses = await asyncio.gather(
            *[client.get(_HN_ITEM_URL.format(sid)) for sid in story_ids[:20]],
            return_exceptions=True,
        )
    for resp in responses:
        if isinstance(resp, Exception):
            continue
        try:
            data = resp.json()
            if not isinstance(data, dict) or data.get("type") != "story":
                continue
            title = (data.get("title") or "").strip()
            if not title:
                continue
            url = data.get("url") or f"https://news.ycombinator.com/item?id={data.get('id')}"
            raw = re.sub(r"<[^>]+>", "", data.get("text") or "")[:500]
            items.append({"source": "hackernews", "title": title, "url": url, "raw_summary": raw})
        except Exception:
            pass

    logger.info("research_agent: HackerNews → %d items", len(items))
    return items


async def _fetch_reddit_items() -> list[dict[str, str]]:
    """Fetch Reddit RSS for AI/robotics/ML subreddits (no API key needed)."""
    items: list[dict[str, str]] = []
    headers = {"User-Agent": "sigmaris-research-bot/1.0 (contact: https://github.com/uthuyomi)"}
    atom_ns = {"atom": "http://www.w3.org/2005/Atom"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), headers=headers) as client:
        for feed_url, source_label in _REDDIT_FEEDS:
            try:
                r = await client.get(feed_url)
                r.raise_for_status()
                root = ET.fromstring(r.text)
                for entry in root.findall("atom:entry", atom_ns):
                    title_el = entry.find("atom:title", atom_ns)
                    link_el = entry.find("atom:link", atom_ns)
                    summary_el = entry.find("atom:summary", atom_ns)
                    if title_el is None:
                        continue
                    title = (title_el.text or "").strip()
                    url = (link_el.get("href") if link_el is not None else "") or ""
                    summary = ""
                    if summary_el is not None and summary_el.text:
                        summary = re.sub(r"<[^>]+>", "", summary_el.text)[:500]
                    if title:
                        items.append({
                            "source": source_label,
                            "title": title,
                            "url": url,
                            "raw_summary": summary,
                        })
            except Exception:
                logger.exception("research_agent: Reddit feed %s failed", feed_url)

    logger.info("research_agent: Reddit → %d items", len(items))
    return items


async def _fetch_news_items() -> list[dict[str, str]]:
    if not settings.news_api_key:
        return []

    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = {
        "q": "人工知能 OR AI OR 機械学習 OR LLM OR ロボティクス",
        "language": "ja",
        "sortBy": "publishedAt",
        "pageSize": "20",
        "from": since,
        "apiKey": settings.news_api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(_NEWSAPI_URL, params=params)
            r.raise_for_status()
    except Exception:
        logger.exception("research_agent: NewsAPI fetch failed")
        return []

    items = []
    for article in r.json().get("articles", []):
        title = (article.get("title") or "").strip()
        url = (article.get("url") or "").strip()
        if not title or not url:
            continue
        items.append({
            "source": "news",
            "title": title[:200],
            "url": url,
            "raw_summary": (article.get("description") or "")[:500],
        })
    logger.info("research_agent: NewsAPI → %d items", len(items))
    return items


# ─── Deduplication ────────────────────────────────────────────────────────────


def _title_similarity(a: str, b: str) -> float:
    def bigrams(s: str) -> set[str]:
        s = re.sub(r"\s+", " ", s.lower().strip())
        return {s[i : i + 2] for i in range(len(s) - 1)}

    ag, bg = bigrams(a), bigrams(b)
    if not ag or not bg:
        return 0.0
    inter = len(ag & bg)
    union = len(ag | bg)
    return inter / union if union > 0 else 0.0


def _deduplicate(
    items: list[dict[str, str]], existing_titles: list[str]
) -> list[dict[str, str]]:
    seen: list[str] = list(existing_titles)
    unique: list[dict[str, str]] = []
    for item in items:
        title = item.get("title", "")
        if any(_title_similarity(title, s) > 0.6 for s in seen):
            continue
        unique.append(item)
        seen.append(title)
    return unique


# ─── Relevance classification ─────────────────────────────────────────────────


async def _classify_items(
    items: list[dict[str, str]],
    user_context: str,
) -> list[dict[str, str]]:
    if not items:
        return []

    router = get_llm_router()
    classified: list[dict[str, str]] = []

    for i in range(0, len(items), 5):
        batch = items[i : i + 5]
        numbered = "\n".join(
            f"{j + 1}. [{item['source']}] {item['title']}\n   {item['raw_summary'][:200]}"
            for j, item in enumerate(batch)
        )
        prompt = (
            f"{user_context}\n\n"
            "以下の記事・リポジトリの関連度を判定してください。\n"
            "基準: 海星さんの趣味・目標、またはシグマリス（家庭支援AI）の設計・運用に関連するか。\n\n"
            f"{numbered}\n\n"
            "JSON形式で返してください:\n"
            '{"results": [{"index": 1, "relevance": "HIGH", "reason": "理由（1文）"}, ...]}\n'
            "relevanceはHIGH/MEDIUM/LOWのどれか。全件分返すこと。"
        )
        try:
            raw = await router.chat(
                TaskType.ROUTING,
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=512,
                json_mode=True,
            )
            data = json.loads(raw)
            result_map = {r["index"]: r for r in data.get("results", [])}
        except Exception:
            logger.exception("research_agent: classification failed for batch at %d", i)
            result_map = {}

        for j, item in enumerate(batch):
            r = result_map.get(j + 1, {})
            classified.append({
                **item,
                "relevance": r.get("relevance", "LOW"),
                "classify_reason": r.get("reason", ""),
            })

    return classified


# ─── Summary generation ───────────────────────────────────────────────────────


async def _summarize_item(item: dict[str, str]) -> str:
    router = get_llm_router()
    try:
        text = await router.chat(
            TaskType.SUMMARIZE,
            [
                {
                    "role": "user",
                    "content": (
                        "以下を日本語で3文以内に要約してください:\n\n"
                        f"タイトル: {item['title']}\n\n{item['raw_summary']}"
                    ),
                }
            ],
            temperature=0.3,
            max_tokens=256,
        )
        return text.strip()
    except Exception:
        logger.exception("research_agent: summarize failed for '%s'", item["title"][:50])
        return (item.get("raw_summary") or "")[:300]


# ─── Perspective generation ───────────────────────────────────────────────────


async def generate_sigmaris_perspective(item: dict[str, Any]) -> str:
    """Generate Sigmaris's first-person comment with narrative context and interest matching."""
    router = get_llm_router()

    profile_ctx = ""
    identity = ""
    narrative_ctx = ""

    async def _load_profile() -> str:
        try:
            jwt = await get_sigmaris_jwt()
            profile = await get_user_profile(jwt)
            return build_profile_context(profile) or ""
        except Exception:
            return ""

    async def _load_narrative() -> str:
        try:
            from app.services.self_narrative import get_current_narrative  # noqa: PLC0415
            n = await get_current_narrative()
            if not n:
                return ""
            return (
                f"前章タイトル: {n.get('title', '')}\n"
                f"内省: {n.get('self_reflection', '')}"
            )
        except Exception:
            return ""

    async def _load_identity() -> str:
        try:
            m = await get_self_model()
            return (m.get("identity_statement", "") if m else "").strip()
        except Exception:
            return ""

    profile_ctx, narrative_ctx, identity = await asyncio.gather(
        _load_profile(), _load_narrative(), _load_identity()
    )

    narrative_section = (
        f"## シグマリスの自己物語（直近）\n{narrative_ctx}\n\n" if narrative_ctx else ""
    )
    prompt = (
        "あなたはシグマリス（家庭支援AI）です。\n"
        f"海星さんの関心領域: {_SIGMARIS_INTERESTS}\n\n"
        + narrative_section
        + f"## シグマリスの自己認識\n{identity}\n\n"
        + (f"## ユーザープロフィール\n{profile_ctx}\n\n" if profile_ctx else "")
        + "以下の記事を見つけました。なぜ今この記事が気になるのかを内省してください。\n"
        "・海星さんの関心や生活との具体的な接点\n"
        "・シグマリス自身の成長・気づきとの関連\n"
        "・「なぜ今なのか」という視点\n"
        "一人称で、自然な日本語で、テンプレート感なく。\n\n"
        f"## 記事情報\n"
        f"ソース: {item.get('source', '')}\n"
        f"タイトル: {item.get('title', '')}\n"
        f"概要: {(item.get('summary') or item.get('raw_summary', ''))[:500]}\n\n"
        "シグマリスのコメント（1〜2文、100文字以内）:"
    )
    try:
        result = await router.chat(
            TaskType.COMPLEX_REASONING,
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=150,
        )
        return result.strip()[:200]
    except Exception:
        logger.exception("research_agent: perspective generation failed")
        return ""


# ─── Main entry point ─────────────────────────────────────────────────────────


async def run_research() -> dict[str, Any]:
    """Fetch research from all sources, classify, summarize, and save to DB."""
    if not settings.research_enabled:
        logger.info("research_agent: RESEARCH_ENABLED=false, skipping")
        return {"ok": True, "skipped": True}

    # Skip if already done today (10+ HIGH items already exist)
    try:
        today_high = await _db_count_today_high()
        if today_high >= 10:
            logger.info(
                "research_agent: task=ROUTING items=0 skipped=all reason=already_done high_today=%d",
                today_high,
            )
            return {"ok": True, "skipped": True, "reason": "already_done"}
    except Exception:
        logger.warning("research_agent: could not check today HIGH count, proceeding")

    user_ctx = "[ユーザープロフィール不明]"
    try:
        jwt = await get_sigmaris_jwt()
        profile = await get_user_profile(jwt)
        user_ctx = build_profile_context(profile) or user_ctx
    except Exception:
        pass

    await _db_delete_expired()

    results = await asyncio.gather(
        _fetch_arxiv_items(),
        _fetch_github_items(),
        _fetch_news_items(),
        _fetch_hn_items(),
        _fetch_reddit_items(),
        return_exceptions=True,
    )
    all_items: list[dict[str, str]] = []
    for batch in results:
        if isinstance(batch, list):
            all_items.extend(batch)

    if not all_items:
        logger.info("research_agent: no items fetched")
        return {"ok": True, "fetched": 0, "saved": 0}

    existing_titles = await _db_get_today_titles()
    unique_items = _deduplicate(all_items, existing_titles)
    logger.info(
        "research_agent: %d items after dedup (from %d raw)",
        len(unique_items), len(all_items),
    )

    classified = await _classify_items(unique_items, user_ctx)

    for item in classified:
        if item.get("relevance") == "HIGH" and item.get("raw_summary"):
            item["summary"] = await _summarize_item(item)
        else:
            item["summary"] = (item.get("raw_summary") or "")[:500]

    saved: list[dict[str, Any]] = []
    for item in classified:
        db_row: dict[str, Any] = {
            "source": item["source"],
            "title": item["title"],
            "url": item["url"],
            "summary": item.get("summary", "")[:2000],
            "relevance": item.get("relevance", "LOW"),
        }
        result = await _db_insert_item(db_row)
        if result:
            saved.append(result)

    high_count = sum(1 for item in classified if item.get("relevance") == "HIGH")

    # Perspective generation: max _MAX_PERSPECTIVES_PER_DAY per day (COMPLEX_REASONING)
    try:
        existing_perspectives = await _db_count_today_perspectives()
    except Exception:
        existing_perspectives = 0
    perspective_budget = max(0, _MAX_PERSPECTIVES_PER_DAY - existing_perspectives)
    perspectives_generated = 0

    for saved_item in saved:
        if saved_item.get("relevance") != "HIGH":
            continue
        if perspectives_generated >= perspective_budget:
            logger.info(
                "research_agent: perspective limit reached (%d/day), skipping remaining",
                _MAX_PERSPECTIVES_PER_DAY,
            )
            break
        try:
            perspective = await generate_sigmaris_perspective(saved_item)
            if perspective:
                await _db_update_perspective(str(saved_item["id"]), perspective)
                saved_item["sigmaris_perspective"] = perspective
                perspectives_generated += 1
        except Exception:
            logger.exception("research_agent: perspective generation raised for item %s", saved_item.get("id"))

    skipped_perspective = high_count - perspectives_generated
    logger.info(
        "research_agent: task=ROUTING items=%d skipped=%d "
        "perspectives=COMPLEX_REASONING count=%d/%d",
        len(saved), len(all_items) - len(unique_items),
        perspectives_generated, _MAX_PERSPECTIVES_PER_DAY,
    )
    return {
        "ok": True,
        "fetched": len(all_items),
        "deduplicated": len(unique_items),
        "saved": len(saved),
        "high": high_count,
        "perspectives_generated": perspectives_generated,
        "perspectives_skipped": skipped_perspective,
    }
