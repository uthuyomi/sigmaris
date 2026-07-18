# 役割: Phase H-3「承認フロー、及び、実際の投稿」の中核オーケストレーション
# ——「海星さんの、明示的な承認によってのみ」、H-2.5の返信案が、実際の
# X投稿(x_publisher.post_tweet())へ渡り得る、唯一の経路。F-3
# (diff_approval.py)の「pending → 人間が明示的に決定する」パターンを、
# そのまま踏襲した(依頼書「重要な制約」への直接対応)。
#
# 【絶対原則(依頼書より、このタスクで最優先)】
# 承認は、必ず、人間による、明示的な操作(approve_reply_draft()を、直接
# 呼び出す)によってのみ、トリガーされる。**本モジュール、および呼び出し
# 先のいずれにも、スケジューラ・定期実行・条件判定による自動承認の経路は
# 存在しない。** reject_reply_draft()は、x_publisher.pyを一切import
# しない・呼び出さない——却下は、記録のみで完結する(F-3のreject_diff_
# proposal()と同じ構造)。
#
# 【@Oyasu1999への返信であっても、承認を省略しない(依頼書要件3)】
# approve_reply_draft()は、reply_draft_audience(developer/general)を
# 一切分岐条件に使わない——H-2のフィルタ判定(developer_bypass/eligible)
# は「返信の対象として扱ってよいか」の判定であり、「実際に投稿してよいか」
# の判定とは、完全に別の話である(依頼書「H-2で、フィルタは、スキップ
# されたが、投稿の、承認は、別の、話であることを、確認すること」への
# 直接対応)。両audienceとも、全く同じapprove_reply_draft()を通る。
#
# 【Constitution・既存フィルタとの連携(F-3のgate A/B二段階を踏襲)】
# constitution_guard.requires_approval("external_transmission")は、常に
# Trueを返す(「ユーザーの許可なき外部送信・投稿」は、S-4の4カテゴリの
# 1つ)——F-3のrequires_approval("code_change")呼び出しと同じ、ドキュメント
# 的な確認呼び出しである。実質的な機械的ゲートは、H-2.5の安全網
# (x_privacy_filter.filter_private_facts/filter_private_info・
# x_content_filter.audit_tweet)であり、以下の2段階で必ず再照合する:
#   段階A: 承認を記録する直前(record_reply_review_decision呼び出し前)
#   段階B: 実際にXへ投稿する直前(post_tweet呼び出し前)
# 段階Bで、万一チェックに失敗した場合(承認から投稿実行までの間に、何ら
# かの理由で対象が変化した等)、**承認の記録自体は取り消さず**(「人間は
# Xを承認した」という事実は、正直な監査証跡として残す)、post_status=
# "blocked_by_recheck"として、実行だけを中断する(F-3の方針4を踏襲)。

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.constitution_guard import requires_approval
from app.services.proactive.jwt_manager import get_sigmaris_jwt
from app.services.x_content_filter import audit_tweet
from app.services.x_privacy_filter import filter_private_facts, filter_private_info
from app.services.x_publisher import get_publisher
from app.services.x_reply_log_store import (
    get_reply_draft_by_id,
    record_reply_post_outcome,
    record_reply_review_decision,
)

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    passed: bool
    reason: str


async def verify_reply_posting_gate(text: str) -> GateResult:
    """Constitution(S-4)の確認と、H-2.5の安全網(プライバシー・品質
    監査)を、1回分、まとめて実行する。承認フローの中で、複数回
    (段階A・段階B)呼び出すための、共通ゲート関数(diff_approval.
    verify_constitution_and_safety_gate()と同じ役割)。"""
    if not requires_approval("external_transmission"):
        return GateResult(
            passed=False,
            reason="constitution_guard.requires_approval('external_transmission')がFalseを返した"
            "(想定外——Constitution定義の変更を確認すること)",
        )

    privacy_ok, detected = filter_private_info(text)
    if not privacy_ok:
        return GateResult(passed=False, reason=f"プライバシー検出: {', '.join(detected)}")

    try:
        jwt = await get_sigmaris_jwt()
    except Exception:
        logger.exception("reply_approval: JWT fetch failed during gate check")
        return GateResult(passed=False, reason="JWT取得に失敗した(記憶プライベート情報チェックを実行できない)")

    facts_ok, blocked = await filter_private_facts(text, jwt)
    if not facts_ok:
        return GateResult(passed=False, reason=f"記憶プライベート情報検出: {', '.join(blocked)}")

    audit_ok, audit_reason, score = await audit_tweet(text)
    if not audit_ok:
        return GateResult(passed=False, reason=f"品質監査不通過(score={score:.1f}): {audit_reason}")

    return GateResult(passed=True, reason="")


@dataclass
class ReplyApprovalOutcome:
    ok: bool
    reply_log_id: str
    status: str  # "approved_and_posted" | "approved_but_blocked" | "rejected" | "rejected_at_gate" | "rejection_failed" | "not_found" | "already_reviewed" | "not_pending_post"
    detail: str = ""
    tweet_id: str = ""


async def approve_reply_draft(reply_log_id: str, *, notes: str = "", reviewed_by: str = "") -> ReplyApprovalOutcome:
    """海星さんの、明示的な承認操作(CLI/APIから、この関数を直接呼び出す
    こと)によってのみ、実行される。この関数だけが、承認確定後に
    x_publisher.post_tweet()を呼び出す経路を持つ。"""
    row = await get_reply_draft_by_id(reply_log_id)
    if row is None:
        return ReplyApprovalOutcome(ok=False, reply_log_id=reply_log_id, status="not_found", detail="対象の返信案が見つからない")

    if row.get("reply_draft_status") != "pending_post":
        return ReplyApprovalOutcome(
            ok=False, reply_log_id=reply_log_id, status="not_pending_post",
            detail=f"reply_draft_status=\"{row.get('reply_draft_status')}\"であり、投稿待ちの返信案ではない",
        )

    if row.get("review_status") != "pending":
        return ReplyApprovalOutcome(
            ok=False, reply_log_id=reply_log_id, status="already_reviewed",
            detail=f"既にreview_status=\"{row.get('review_status')}\"であり、pending状態ではない",
        )

    draft_text = str(row.get("reply_draft_text") or "")
    if not draft_text:
        return ReplyApprovalOutcome(
            ok=False, reply_log_id=reply_log_id, status="rejected_at_gate", detail="返信案テキストが空である",
        )

    # 段階A: 承認を記録する直前のゲート
    gate_a = await verify_reply_posting_gate(draft_text)
    if not gate_a.passed:
        logger.warning("reply_approval: gate A failed for id=%s — %s", reply_log_id, gate_a.reason)
        return ReplyApprovalOutcome(ok=False, reply_log_id=reply_log_id, status="rejected_at_gate", detail=gate_a.reason)

    recorded = await record_reply_review_decision(reply_log_id, status="approved", notes=notes, reviewed_by=reviewed_by)
    if not recorded:
        return ReplyApprovalOutcome(
            ok=False, reply_log_id=reply_log_id, status="rejected_at_gate", detail="承認の記録(DB書き込み)に失敗した",
        )

    # 段階B: 実際にXへ投稿する直前のゲート(承認の記録は取り消さない)。
    gate_b = await verify_reply_posting_gate(draft_text)
    if not gate_b.passed:
        logger.error(
            "reply_approval: gate B (post-approval re-check) failed for id=%s — %s. "
            "承認は記録済みだが、投稿を中断する。",
            reply_log_id, gate_b.reason,
        )
        await record_reply_post_outcome(reply_log_id, status="blocked_by_recheck", error=gate_b.reason)
        return ReplyApprovalOutcome(
            ok=False, reply_log_id=reply_log_id, status="approved_but_blocked",
            detail=f"承認は記録されたが、投稿直前の再チェックで中断した: {gate_b.reason}",
        )

    in_reply_to_tweet_id = row.get("reply_tweet_id")
    publisher = get_publisher()
    tweet_id = await publisher.post_tweet(draft_text, in_reply_to_tweet_id=in_reply_to_tweet_id)

    if tweet_id is None:
        await record_reply_post_outcome(reply_log_id, status="failed_to_post", error="post_tweet()がNoneを返した")
        return ReplyApprovalOutcome(
            ok=False, reply_log_id=reply_log_id, status="approved_but_blocked",
            detail="承認は記録されたが、X投稿(post_tweet)が失敗した",
        )

    await record_reply_post_outcome(reply_log_id, status="posted", tweet_id=tweet_id)
    return ReplyApprovalOutcome(
        ok=True, reply_log_id=reply_log_id, status="approved_and_posted", tweet_id=tweet_id,
    )


async def reject_reply_draft(reply_log_id: str, *, notes: str = "", reviewed_by: str = "") -> ReplyApprovalOutcome:
    """海星さんの、明示的な却下操作によってのみ、実行される。**この関数
    は、x_publisher.pyを一切importしない・呼び出さない**——却下は常に、
    記録のみで完結する(モジュールdocstring参照)。"""
    row = await get_reply_draft_by_id(reply_log_id)
    if row is None:
        return ReplyApprovalOutcome(ok=False, reply_log_id=reply_log_id, status="not_found", detail="対象の返信案が見つからない")

    if row.get("review_status") != "pending":
        return ReplyApprovalOutcome(
            ok=False, reply_log_id=reply_log_id, status="already_reviewed",
            detail=f"既にreview_status=\"{row.get('review_status')}\"であり、pending状態ではない",
        )

    recorded = await record_reply_review_decision(reply_log_id, status="rejected", notes=notes, reviewed_by=reviewed_by)
    if not recorded:
        return ReplyApprovalOutcome(
            ok=False, reply_log_id=reply_log_id, status="rejection_failed", detail="却下の記録(DB書き込み)に失敗した",
        )

    return ReplyApprovalOutcome(ok=True, reply_log_id=reply_log_id, status="rejected", detail=notes)
