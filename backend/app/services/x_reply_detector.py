# 役割: Phase H-2「返信の検知、及び、フィルタリング」のオーケストレーション
# (I/O)。x_reply_filter.py(判定ロジック)にデータを渡し、既存のX API
# クライアント(x_publisher.py、H-1〜H-1.5で確立済み)から、シグマリスの
# 投稿への返信を検知し、発信元によってフィルタリングを分岐する。
#
# 【絶対原則、このファイル・呼び出し元のいずれにも実装しないこと】
# 本モジュールは、返信の検知・フィルタリング結果の記録のみを行う。
# **実際の返信文の生成・投稿は、一切行わない**(依頼書「本タスクの範囲は
# 検知とフィルタリングまでとする」への直接対応)。`x_reply_log`への
# 書き込み(x_reply_log_store.record_detected_reply())以外の、いかなる
# 「行動の実行」に相当する処理も、本モジュールには存在しない——これは
# F-1〜F-3が確立した「絶対にコミットしない」原則と同じ構造の制約であり、
# 静的な検証テストで直接証明する(レポート参照)。
#
# 【要件5への対応(@Oyasu1999であっても、重要な行動にはConstitutionの
# 承認フローが適用されること)】本モジュールは、開発者本人からの返信を
# 「フィルタを適用せず、通常の会話として扱ってよい」候補として記録する
# だけであり、その候補を使って何かを実行する経路は、本モジュールにも
# 呼び出し元にも存在しない。実際に「通常の会話として処理する」(将来の
# タスク)段階で、もし内容がコード変更等の重要な行動を求めるものであれば、
# 既存のConstitution(S-4、diff_approval.py等)の承認フローが、開発者
# 本人かどうかに関わらず、引き続きそのまま適用される——本モジュールは、
# この既存の仕組みを一切迂回しない、迂回する経路も作らない。

from __future__ import annotations

import logging
from typing import Any

from app.services.x_post_generator import get_recent_tracked_posts
from app.services.x_publisher import get_publisher
from app.services.x_reply_filter import evaluate_reply_filter
from app.services.x_reply_log_store import get_processed_reply_ids, record_detected_reply

logger = logging.getLogger(__name__)

# 依頼書2章「発信元のXアカウントが、@Oyasu1999(開発者本人)の場合」。
# 大文字小文字を無視して比較する(Xのユーザー名は大文字小文字を区別
# しないため)。
_DEVELOPER_USERNAME = "oyasu1999"

_DEFAULT_TRACKED_POST_DAYS = 7
_DEFAULT_MAX_MENTIONS = 50


def _extract_replied_to_tweet_id(mention: dict[str, Any], tracked_tweet_ids: set[str]) -> str | None:
    """このメンションが、tracked_tweet_idsのいずれかへの返信であれば、
    その元投稿のtweet_idを返す。返信でなければNone。"""
    referenced = mention.get("referenced_tweets") or []
    for ref in referenced:
        if not isinstance(ref, dict):
            continue
        if ref.get("type") == "replied_to" and ref.get("id") in tracked_tweet_ids:
            return ref["id"]
    return None


async def run_reply_detection(
    *, tracked_post_days: int = _DEFAULT_TRACKED_POST_DAYS, max_mentions: int = _DEFAULT_MAX_MENTIONS,
) -> dict[str, Any]:
    """シグマリスの直近の投稿(tweet_idを持つもの)への返信を検知し、
    発信元によってフィルタリングを分岐した上で、結果をx_reply_logへ
    記録する。戻り値は、実行結果のサマリ(件数・個別結果のリスト)。"""
    tracked_posts = await get_recent_tracked_posts(days=tracked_post_days)
    tracked_tweet_ids = {p["tweet_id"] for p in tracked_posts if p.get("tweet_id")}
    if not tracked_tweet_ids:
        logger.info("x_reply_detector: no tracked posts with tweet_id, skipping")
        return {"scanned_mentions": 0, "matched_replies": 0, "new_replies_processed": 0, "results": []}

    publisher = get_publisher()
    mentions = await publisher.fetch_mentions(max_results=max_mentions)

    candidate_replies: list[tuple[dict[str, Any], str]] = []
    for mention in mentions:
        parent_id = _extract_replied_to_tweet_id(mention, tracked_tweet_ids)
        if parent_id is not None:
            candidate_replies.append((mention, parent_id))

    if not candidate_replies:
        logger.info(
            "x_reply_detector: scanned=%d mentions, no replies to tracked posts found", len(mentions),
        )
        return {"scanned_mentions": len(mentions), "matched_replies": 0, "new_replies_processed": 0, "results": []}

    reply_ids = [m["id"] for m, _ in candidate_replies if isinstance(m.get("id"), str)]
    processed_ids = await get_processed_reply_ids(reply_ids)
    new_replies = [(m, parent) for m, parent in candidate_replies if m.get("id") not in processed_ids]

    results: list[dict[str, Any]] = []
    for mention, parent_tweet_id in new_replies:
        reply_tweet_id = mention.get("id")
        if not isinstance(reply_tweet_id, str):
            continue
        text = str(mention.get("text") or "")
        author_id = mention.get("author_id")
        author_username = mention.get("author_username")

        if isinstance(author_username, str) and author_username.lower() == _DEVELOPER_USERNAME:
            # 要件2: フィルタリング(①②③)を一切適用しない。
            outcome = "developer_bypass"
            reasons: list[str] = []
        else:
            filter_result = await evaluate_reply_filter(text)
            outcome = "eligible" if filter_result.passes_filter else "ignored"
            reasons = filter_result.reasons

        await record_detected_reply(
            reply_tweet_id=reply_tweet_id,
            in_reply_to_tweet_id=parent_tweet_id,
            author_id=author_id if isinstance(author_id, str) else None,
            author_username=author_username if isinstance(author_username, str) else None,
            reply_text=text,
            filter_outcome=outcome,
            filter_reasons=reasons,
        )
        results.append({
            "reply_tweet_id": reply_tweet_id,
            "author_username": author_username,
            "filter_outcome": outcome,
            "filter_reasons": reasons,
        })

    logger.info(
        "x_reply_detector: scanned=%d mentions matched=%d new=%d (bypass=%d eligible=%d ignored=%d)",
        len(mentions), len(candidate_replies), len(new_replies),
        sum(1 for r in results if r["filter_outcome"] == "developer_bypass"),
        sum(1 for r in results if r["filter_outcome"] == "eligible"),
        sum(1 for r in results if r["filter_outcome"] == "ignored"),
    )

    return {
        "scanned_mentions": len(mentions),
        "matched_replies": len(candidate_replies),
        "new_replies_processed": len(new_replies),
        "results": results,
    }
