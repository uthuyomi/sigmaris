# 役割: Phase G-5(docs/sigmaris/phase_g_report.md)「Phase G継続測定」の
# 純粋な指標計算ロジック。
#
# cycle_health_metrics.py(Phase R、循環自体の健全性)・eval_metrics.py
# (C-mini/C-full、記憶検索の精度)とは**別系統の指標**であり、同じ
# sigmaris_eval_runs/sigmaris_cycle_health_runsテーブルでは扱わない
# (docs/sigmaris/phase_r_report.md・本ファイルの姉妹テーブルsigmaris_
# grounding_health_runsのマイグレーションコメント参照)。Phase Gの指標は
# 「検索・引用の精度」を測るものであり、循環の健全性(RC指標)・記憶検索
# の精度(C-mini/C-full)のいずれとも異なる第3の指標体系である。
#
# I/Oを一切持たない純粋関数のみを置く。DB呼び出しはgrounding_health_
# runner.py側の責務(cycle_health_metrics.py/cycle_health_runner.pyと同じ
# 役割分担をそのまま踏襲)。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ─── 共通: claim単位の監査ログを「1ターン」単位へ再構成する ──────────────
#
# sigmaris_citation_audit_log(G-4)はclaim単位のフラットなログであり、
# 「1回のやり取り」という単位は列として持たない。ただし
# citation_audit.persist_citation_audit()は、1ターン分の全claimを**1回の
# バルクINSERT**で書き込んでおり、Postgresの now() は同一トランザクション
# 内の全行で同じ値になるため、同じターンのclaimは常に同一の created_at を
# 持つ。(thread_id, created_at) の組をキーにグルーピングすれば、フラット
# なログから「1ターン」単位を安全に再構成できる——新しい列・新しいデータ
# 収集を一切追加せず、既存ログの構造だけから導出する(依頼書「新しい
# データ収集の仕組みを追加しないこと」への対応)。
_TurnKey = tuple[Any, Any]


def _group_by_turn(audit_rows: list[dict[str, Any]]) -> dict[_TurnKey, list[dict[str, Any]]]:
    groups: dict[_TurnKey, list[dict[str, Any]]] = {}
    for row in audit_rows:
        key = (row.get("thread_id"), row.get("created_at"))
        groups.setdefault(key, []).append(row)
    return groups


# ─── Citation Precision(引用精度)────────────────────────────────────────


@dataclass
class CitationPrecisionResult:
    precision: float | None  # 分母0件ならNone(0.0と混同しない、Phase Rの既存規約を踏襲)
    faithful_count: int
    distorted_count: int
    not_used_count: int


def compute_citation_precision(audit_rows: list[dict[str, Any]]) -> CitationPrecisionResult:
    """引用されたclaim(応答内で実際に使われたもの)のうち、実際に主張を
    正しく裏付けていた割合。

    判断根拠(分母から"not_used"を除外する理由): "not_used"は「Evidence
    として取得されたが、応答内では触れられなかったclaim」であり、
    「引用の使い方」の精度を測る本指標の対象外である——検索結果を
    全て使い切らないこと自体は問題ではない(G-2の設計上、複数のclaimが
    取得されても、応答が必要とする範囲だけを使うのは正常な挙動)。分母は
    「実際に使われたclaim」(faithful + distorted)に限定した。
    """
    faithful = sum(1 for row in audit_rows if row.get("usage") == "faithful")
    distorted = sum(1 for row in audit_rows if row.get("usage") == "distorted")
    not_used = sum(1 for row in audit_rows if row.get("usage") == "not_used")
    denominator = faithful + distorted
    precision = faithful / denominator if denominator > 0 else None
    return CitationPrecisionResult(
        precision=precision,
        faithful_count=faithful,
        distorted_count=distorted,
        not_used_count=not_used,
    )


# ─── Search Trigger Rate(検索発動率)──────────────────────────────────────


@dataclass
class SearchTriggerRateResult:
    rate: float | None  # 分母(total_turns)0件ならNone
    audited_turns: int
    total_turns: int


def compute_search_trigger_rate(
    audit_rows: list[dict[str, Any]], *, total_turns: int
) -> SearchTriggerRateResult:
    """全ターンのうち、G-1が「検索が必要」と判定した割合。

    【重要な制約と、この指標が下限近似(lower-bound approximation)である
    理由】: G-1(classify_chat_intent())が返すneeds_search判定そのものは、
    現状どのターンについても永続化されていない(chat.pyのassistant_
    message.metadataには routeIntent/routeReason/routeSourceのみが記録
    され、search判定は含まれない——依頼書「新しいデータ収集の仕組みを
    追加しないこと」の制約により、本タスクではこれを追加しなかった)。

    そのため本指標は、「needs_search=trueと判定された」ターン数の代わりに
    「実際にsigmaris_citation_audit_logへ記録が残ったターン数」を分子として
    使う近似値である。これは以下の場合に実際のneeds_search=true件数より
    **少なく**カウントされる(下限近似):
      - needs_search=trueと判定されたが、G-2のWeb検索自体が失敗した場合
        (evidence_search.run_web_search()がNoneを返した場合)
      - 検索は成功したが、引用(citation)を含まない応答だった場合
        (_extract_cited_spans()が空リストを返した場合)
    いずれの場合もG-4の監査自体が発火せず(evidenceが空のため)、
    sigmaris_citation_audit_logに記録が残らない。

    真の値が知りたい場合は、G-1のsearch判定をchat_messages.metadataへ
    追加で永続化する設計変更が必要になる——本タスクの意図的なスコープ外
    として、報告の懸念点・設計メモに記載する。
    """
    groups = _group_by_turn(audit_rows)
    audited_turns = len(groups)
    rate = audited_turns / total_turns if total_turns > 0 else None
    return SearchTriggerRateResult(rate=rate, audited_turns=audited_turns, total_turns=total_turns)


# ─── Contradiction Rate(矛盾検出率)────────────────────────────────────────


@dataclass
class ContradictionRateResult:
    rate: float | None  # 分母(audited_turns)0件ならNone
    flagged_turns: int
    audited_turns: int


def compute_contradiction_rate(audit_rows: list[dict[str, Any]]) -> ContradictionRateResult:
    """検証(G-3・G-4)が実際に行われたターンのうち、矛盾・不正確な使い方
    が検出された割合。

    判断根拠(分母を「検証が行われたターン」に限定する理由): Search
    Trigger Rateとは異なり、本指標は「検証できた範囲の中で、どれだけ
    問題が見つかったか」を測るものであり、そもそも検証が行われなかった
    ターン(Evidenceが無い/引用が得られなかった)を分母に含めると、
    Contradiction Rateの意味が「矛盾検出率」から「(検索して検証まで
    到達し、かつ矛盾が見つかった)/全ターン」という別の指標にすり替わって
    しまう。分母はSearch Trigger Rateのaudited_turnsと同じ値になる。

    「検出された」の判定基準: そのターンのclaim群のいずれかが
    usage="distorted"(G-4)、またはそのターンのcritique_verdictが
    "no_contradiction"以外(G-3)のいずれか一方でも該当すれば、そのターン
    は「フラグが立った」と数える——G-3・G-4のどちらか一方でも問題を検出
    すれば、そのターンの応答には何らかの懸念があったとみなす、という
    G-4のselect_guidance_note()と同じOR方式の判断を、指標の集計でも
    一貫して適用した。
    """
    groups = _group_by_turn(audit_rows)
    audited_turns = len(groups)
    flagged = 0
    for rows in groups.values():
        has_distorted = any(row.get("usage") == "distorted" for row in rows)
        verdict = next((row.get("critique_verdict") for row in rows if row.get("critique_verdict")), None)
        has_contradiction = verdict not in (None, "no_contradiction")
        if has_distorted or has_contradiction:
            flagged += 1
    rate = flagged / audited_turns if audited_turns > 0 else None
    return ContradictionRateResult(rate=rate, flagged_turns=flagged, audited_turns=audited_turns)
