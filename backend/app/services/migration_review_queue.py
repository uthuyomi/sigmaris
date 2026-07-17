# 役割: Phase E-4「マイグレーションを伴う仮説の、正式な人間レビュー待ち
# キュー」の純粋なロジック(I/Oなし)。
#
# 【背景】E-1(static_verification.py::mentions_migration())・E-2は、
# マイグレーションに言及する仮説を、自動検証パイプラインから「除外」
# するだけで、その後の扱いを定義していなかった。本モジュールは、この
# "除外"という回避策から一歩進み、除外された仮説を、人間が判断するために
# 必要な情報とともに、専用のキューへ集約する形式を定義する。
#
# 【重要な制約(依頼書「過度な自動化を避けること」)】本モジュールは、
# キューへの記録・レビュー状態の管理のみを行う。マイグレーションの
# 自動適用・自動承認・自動ロールバックの仕組みは、一切実装しない
# ——承認・却下は、常に人間が`record_review_decision()`(store層)を
# 明示的に呼ぶことでのみ行われる。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# review_statusの取りうる値。デフォルトは常にpending——自動承認・自動
# 却下の経路は存在しない(依頼書「過度な自動化を避けること」への対応)。
REVIEW_STATUSES: frozenset[str] = frozenset({"pending", "approved", "rejected"})
_DEFAULT_REVIEW_STATUS = "pending"


@dataclass
class MigrationReviewEntry:
    """1件のマイグレーション言及仮説を、人間がレビューするために必要な
    情報にまとめたもの。D-3のphase_e_handoff(Phase D-3報告書20章が
    設計したPhase Eへの引き渡し形式)から仮説の内容を、E-1のstatic_
    verification行からマイグレーション判定の理由を、それぞれそのまま
    引用する——新しい要約・言い換えのロジックは追加しない。"""

    hypothesis_id: str | None
    hypothesis_priority_id: str | None
    static_verification_id: str | None

    title: str
    what_is_problem: str
    why_problem: str
    how_to_improve: str
    migration_reason: str  # E-1のmentions_migration()が検出したキーワードとその理由

    source_evidence: dict[str, Any] = field(default_factory=dict)
    expected_metric_improvements: list[str] = field(default_factory=list)
    d3_priority_rank: int | None = None
    d3_priority_score: int | None = None

    review_status: str = _DEFAULT_REVIEW_STATUS


def build_review_entry(
    static_verification_row: dict[str, Any], priority_row: dict[str, Any] | None
) -> MigrationReviewEntry | None:
    """E-1のsigmaris_static_verifications行(verdict="excluded_migration"
    のもの)と、対応するD-3のsigmaris_hypothesis_priorities行から、1件の
    レビューキューエントリを組み立てる。

    判断根拠(phase_e_handoffから仮説内容を取る理由): D-3のbuild_phase_e_
    handoff()(hypothesis_prioritization.py)が、既にPhase Eが必要とする
    仮説内容(title/what_is_problem/why_problem/how_to_improve/
    source_evidence/expected_metric_improvements)を1つのjsonbへ集約
    済みである。sigmaris_hypothesesへ改めて問い合わせる代わりに、この
    既存の集約結果をそのまま再利用した——依頼書「既存資産の再利用」の
    徹底。

    priority_rowが存在しない(D-3側の記録が見つからない、または
    phase_e_handoffが空)場合はNoneを返す——仮説の内容が分からないまま
    「マイグレーションを含む何か」とだけキューへ積んでも、人間が判断
    できないため、意味のあるエントリを組み立てられない場合は諦める
    (無理に空欄のまま積まない、という判断)。
    """
    if priority_row is None:
        return None
    handoff = priority_row.get("phase_e_handoff")
    if not isinstance(handoff, dict) or not handoff:
        return None

    title = str(handoff.get("title") or "").strip()
    if not title:
        return None

    return MigrationReviewEntry(
        hypothesis_id=static_verification_row.get("hypothesis_id"),
        hypothesis_priority_id=static_verification_row.get("hypothesis_priority_id"),
        static_verification_id=static_verification_row.get("id"),
        title=title,
        what_is_problem=str(handoff.get("what_is_problem") or ""),
        why_problem=str(handoff.get("why_problem") or ""),
        how_to_improve=str(handoff.get("how_to_improve") or ""),
        migration_reason=str(static_verification_row.get("reason") or ""),
        source_evidence=handoff.get("source_evidence") if isinstance(handoff.get("source_evidence"), dict) else {},
        expected_metric_improvements=(
            list(handoff.get("expected_metric_improvements"))
            if isinstance(handoff.get("expected_metric_improvements"), list)
            else []
        ),
        d3_priority_rank=priority_row.get("priority_rank"),
        d3_priority_score=priority_row.get("priority_score"),
    )


def select_new_migration_entries(
    static_verification_rows: list[dict[str, Any]],
    priority_rows: list[dict[str, Any]],
    *,
    already_queued_hypothesis_ids: set[str],
) -> list[MigrationReviewEntry]:
    """verdict="excluded_migration"の行から、まだキューに存在しない
    ものだけを抽出し、レビューエントリを組み立てる。

    判断根拠(重複防止): E-1は繰り返し実行されるCLIであり、同じ仮説が
    複数回のE-1実行にわたって"excluded_migration"と判定され続ける
    (D-3の優先順位付けで上位に居続ける限り)。既にキューに積まれている
    hypothesis_idは、その仮説が既に人間の目に触れている(pending/
    approved/rejectedのいずれか)ことを意味するため、再度積まない
    ——依頼書が意図する「明確なワークフロー」を、重複エントリで
    薄めないための判断。
    """
    priority_by_id = {row["id"]: row for row in priority_rows if row.get("id")}

    entries: list[MigrationReviewEntry] = []
    seen_in_this_batch: set[str] = set()
    for row in static_verification_rows:
        if row.get("verdict") != "excluded_migration":
            continue
        hyp_id = row.get("hypothesis_id")
        if not hyp_id or hyp_id in already_queued_hypothesis_ids or hyp_id in seen_in_this_batch:
            continue

        priority_row = priority_by_id.get(row.get("hypothesis_priority_id"))
        entry = build_review_entry(row, priority_row)
        if entry is None:
            continue
        entries.append(entry)
        seen_in_this_batch.add(hyp_id)

    return entries
