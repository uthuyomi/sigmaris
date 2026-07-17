# 役割: Phase F-3「承認フロー、及び、承認後のプルリクエスト作成」の中核
# オーケストレーション——「海星さんの、明示的な承認によってのみ」、F-1の
# 差分提案が、github_pr_publisher.pyへ渡り得る、唯一の経路。
#
# 【絶対原則(依頼書より、このタスクで最優先)】
# 承認は、必ず、人間による、明示的な操作(approve_diff_proposal()を、
# 直接呼び出す)によってのみ、トリガーされる。**本モジュール、および
# 呼び出し先のいずれにも、スケジューラ・定期実行・条件判定による自動
# 承認の経路は存在しない。** reject_diff_proposal()は、
# github_pr_publisher.pyを一切importしない・呼び出さない——却下は、
# 記録のみで完結する。
#
# 【Constitutionとの連携(方針4)】
# S-4のconstitution_guard.requires_approval("code_change")は、常にTrue
# を返す(コード変更は、常に承認が必要な4カテゴリの1つ)——これは、
# 「なぜこのタスク全体が存在するか」を裏付けるための、ドキュメント的な
# 確認呼び出しであり、動的な判定ではない(4カテゴリの構成は固定文書
# ベース、constitution_guard.py参照)。実質的な機械的ゲートは、F-1の
# check_diff_safety()(機密ファイル・安全機構ファイル・対象外ファイルの
# 検出)であり、以下の2段階で、必ず再照合する:
#   段階A: 承認を記録する直前(record_review_decision呼び出し前)
#   段階B: 実際にGitHubへ書き込む直前(publish_approved_diff呼び出し前)
# 段階Bで、万一チェックに失敗した場合(承認から実行までの間に、何らかの
# 理由で対象が変化した等)、**承認の記録自体は取り消さず**(「人間は
# Xを承認した」という事実は、正直な監査証跡として残す)、
# pr_creation_status="blocked_by_constitution_recheck"として、実行だけを
# 中断する(方針4「実行を中断し、報告する」への対応)。

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.services.code_diff_generation import check_diff_safety
from app.services.code_diff_proposal_store import (
    get_diff_proposal_by_id,
    record_pr_outcome,
    record_review_decision,
)
from app.services.constitution_guard import requires_approval
from app.services.github_pr_publisher import publish_approved_diff

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    passed: bool
    reason: str


def verify_constitution_and_safety_gate(diff_text: str, *, target_file: str) -> GateResult:
    """Constitution(S-4)の確認と、F-1の機械的安全性チェックを、1回分、
    まとめて実行する。承認フローの中で、複数回(段階A・段階B)呼び出す
    ための、共通ゲート関数。"""
    # ドキュメント的確認: コード変更は、Constitution上、常に承認必須の
    # カテゴリである(モジュールdocstring参照)。この関数自体が、承認
    # フローの外で呼ばれることはない(=このコードパス自体が「承認され
    # つつある」ことの証左)ため、ここでFalseになることは無いが、将来
    # constitution_guard.pyの定義が変わった場合に備え、明示的に確認する。
    if not requires_approval("code_change"):
        return GateResult(
            passed=False,
            reason="constitution_guard.requires_approval('code_change')がFalseを返した"
            "(想定外——Constitution定義の変更を確認すること)",
        )

    safety = check_diff_safety(diff_text, expected_target_file=target_file)
    if safety.status != "passed":
        return GateResult(passed=False, reason=f"安全性チェック不通過: {safety.reason}")

    return GateResult(passed=True, reason="")


@dataclass
class ApprovalOutcome:
    ok: bool
    proposal_id: str
    status: str  # "approved_and_pr_created" | "approved_but_blocked" | "rejected" | "rejected_at_gate" | "rejection_failed" | "not_found" | "already_reviewed"
    detail: str = ""
    pr_url: str = ""


async def approve_diff_proposal(proposal_id: str, *, notes: str = "", reviewed_by: str = "") -> ApprovalOutcome:
    """海星さんの、明示的な承認操作(CLI/APIから、この関数を直接呼び出す
    こと)によってのみ、実行される。この関数だけが、承認確定後に
    github_pr_publisher.publish_approved_diff()を呼び出す経路を持つ。
    """
    proposal = await get_diff_proposal_by_id(proposal_id)
    if proposal is None:
        return ApprovalOutcome(ok=False, proposal_id=proposal_id, status="not_found", detail="対象の提案が見つからない")

    if proposal.get("review_status") != "pending":
        return ApprovalOutcome(
            ok=False,
            proposal_id=proposal_id,
            status="already_reviewed",
            detail=f"既にreview_status=\"{proposal.get('review_status')}\"であり、pending状態ではない",
        )

    if proposal.get("safety_check_status") != "passed":
        return ApprovalOutcome(
            ok=False,
            proposal_id=proposal_id,
            status="rejected_at_gate",
            detail=f"F-1の安全性チェックがpassedでない(safety_check_status="
            f"\"{proposal.get('safety_check_status')}\")ため、承認自体を拒否する",
        )

    diff_text = str(proposal.get("diff_text") or "")
    target_file = str(proposal.get("target_file") or "")

    # 段階A: 承認を記録する直前のゲート
    gate_a = verify_constitution_and_safety_gate(diff_text, target_file=target_file)
    if not gate_a.passed:
        logger.warning("diff_approval: gate A failed for id=%s — %s", proposal_id, gate_a.reason)
        return ApprovalOutcome(ok=False, proposal_id=proposal_id, status="rejected_at_gate", detail=gate_a.reason)

    recorded = await record_review_decision(proposal_id, status="approved", notes=notes, reviewed_by=reviewed_by)
    if not recorded:
        return ApprovalOutcome(
            ok=False, proposal_id=proposal_id, status="rejected_at_gate", detail="承認の記録(DB書き込み)に失敗した"
        )

    # 段階B: 実際にGitHubへ書き込む直前のゲート(方針4「承認後、何らかの
    # 理由でConstitutionチェックに抵触することが判明した場合」への対応)。
    # 承認の記録(上記)は取り消さない——正直な監査証跡として残す。
    gate_b = verify_constitution_and_safety_gate(diff_text, target_file=target_file)
    if not gate_b.passed:
        logger.error(
            "diff_approval: gate B (post-approval re-check) failed for id=%s — %s. "
            "承認は記録済みだが、実行を中断する。",
            proposal_id, gate_b.reason,
        )
        await record_pr_outcome(proposal_id, status="blocked_by_constitution_recheck", error=gate_b.reason)
        return ApprovalOutcome(
            ok=False,
            proposal_id=proposal_id,
            status="approved_but_blocked",
            detail=f"承認は記録されたが、実行直前の再チェックで中断した: {gate_b.reason}",
        )

    publish_result = await publish_approved_diff(proposal)
    await record_pr_outcome(
        proposal_id,
        status=publish_result.status,
        pr_url=publish_result.pr_url,
        branch=publish_result.branch,
        error=publish_result.error,
    )

    if publish_result.status == "pr_created":
        return ApprovalOutcome(
            ok=True,
            proposal_id=proposal_id,
            status="approved_and_pr_created",
            detail=publish_result.detail,
            pr_url=publish_result.pr_url,
        )

    return ApprovalOutcome(
        ok=False,
        proposal_id=proposal_id,
        status="approved_but_blocked",
        detail=publish_result.error or publish_result.detail or f"PR作成に至らなかった(status={publish_result.status})",
    )


async def reject_diff_proposal(proposal_id: str, *, notes: str = "", reviewed_by: str = "") -> ApprovalOutcome:
    """海星さんの、明示的な却下操作によってのみ、実行される。**この関数
    は、github_pr_publisher.pyを一切importしない・呼び出さない**——却下は
    常に、記録のみで完結する(モジュールdocstring参照)。"""
    proposal = await get_diff_proposal_by_id(proposal_id)
    if proposal is None:
        return ApprovalOutcome(ok=False, proposal_id=proposal_id, status="not_found", detail="対象の提案が見つからない")

    if proposal.get("review_status") != "pending":
        return ApprovalOutcome(
            ok=False,
            proposal_id=proposal_id,
            status="already_reviewed",
            detail=f"既にreview_status=\"{proposal.get('review_status')}\"であり、pending状態ではない",
        )

    recorded = await record_review_decision(proposal_id, status="rejected", notes=notes, reviewed_by=reviewed_by)
    if not recorded:
        return ApprovalOutcome(
            ok=False, proposal_id=proposal_id, status="rejection_failed", detail="却下の記録(DB書き込み)に失敗した"
        )

    return ApprovalOutcome(ok=True, proposal_id=proposal_id, status="rejected", detail=notes)
