# 役割: Phase D-3「優先順位付け・検証可能性の評価」の純粋なロジック
# (I/Oなし、新規LLM呼び出しなし)。D-2が生成・保存した仮説
# (sigmaris_hypotheses)を入力に、
#   1. 検証可能性の評価(expected_metric_improvementsが、既知の測定可能な
#      指標を具体的に指しているかを、ルールベースで判定)
#   2. 優先順位付け(D-1由来のevidence_priority_score + D-2由来の指標の
#      具体性を単純加算し、検証可能性を最優先の並べ替え軸にする)
#   3. requires_special_reviewの仮説を、通常の優先順位付けから完全に
#      分離する
#   4. Phase Eへの引き渡し形式(データ構造)の組み立て
# を行う。
#
# 【重要】新しいスコアリングモデル・機械学習は導入しない(依頼書の制約)。
# 既存のD-1(evidence_aggregation.py)・D-2(hypothesis_generation.py)が
# 確立した「シンプルな加算・単純な二段階ソート」という設計をそのまま
# 踏襲した。新規LLM呼び出しも行わない——「検証可能性」の評価対象は
# D-2が既に生成・保存済みのexpected_metric_improvementsであり(依頼書
# 2章「これが実行された場合...を明確に言語化させる」は既にD-2の生成
# プロンプトが満たしている)、D-3の役割はその**既存の出力を評価する**
# ことにとどまる、という判断(判断根拠、レポート参照)。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Phase R(RC指標)・Phase G(Grounding指標)・C-mini/C-full(eval_metrics.py)
# が実際に使っている指標名を、そのまま「測定可能な指標」の語彙として
# 再利用した——新しい指標カタログを作らず、既存の3系統の指標名をそのまま
# 引用する判断(依頼書「既存資産の再利用」の徹底)。表記ゆれ(RC-1 / rc1 /
# rc1_eligible_completion_rate等)を許容するため、部分一致で判定する。
_MEASURABLE_METRIC_VOCABULARY: tuple[str, ...] = (
    # Phase R (docs/sigmaris/phase_r_report.md, cycle_health_runs_store.py)
    "rc-1", "rc1", "eligible_completion_rate", "circulation completion",
    "rc-2", "rc2", "temporal consistency",
    "rc-3", "rc3", "belief stability",
    "rc-4", "rc4", "policy-belief alignment", "policy belief alignment",
    "rc-5", "rc5", "cycle break",
    # Phase G (docs/sigmaris/phase_g_report.md, grounding_health_runs_store.py)
    "citation precision", "citation_precision",
    "search trigger rate", "search_trigger_rate",
    "contradiction rate", "contradiction_rate",
    # C-mini/C-full (eval_metrics.py)
    "memory_precision", "memory precision",
    "memory_recall", "memory recall",
    "response_error_rate", "response error rate",
    "memory_duplicate_rate", "memory duplicate rate", "duplicate_rate",
)

# D-2側のfinalize_hypothesis()が既に「how_to_improveが抽象的すぎないか」
# (evidence_aggregation.pyのis_vague_or_unsupported())を検証済みのため、
# D-3ではその軸を再チェックしない——D-3固有の新しい評価軸(measurable
# outcomeの有無)だけに責務を絞る、という重複回避の判断。


@dataclass
class VerifiabilityResult:
    checkable: bool
    matched_metrics: list[str]
    reason: str


def assess_verifiability(hypothesis: dict[str, Any]) -> VerifiabilityResult:
    """expected_metric_improvementsが、既知の測定可能な指標を具体的に
    指しているかを判定する。

    判定基準(依頼書2章「具体的で、測定可能な形になっているか」への対応):
    1. expected_metric_improvementsが空 → 検証不能(予測が一切無い)
    2. 値はあるが、いずれも既知の指標語彙と一致しない
       (例:「使い勝手」「品質」のような主観的な言葉のみ) → 検証不能
    3. 既知の指標に1件以上一致する → 検証可能

    意味解析は行わない、部分一致のみの単純な判定(依頼書「新しい
    スコアリングモデル・複雑な機械学習は導入しない」への対応)。
    """
    raw = hypothesis.get("expected_metric_improvements")
    candidates = [str(m) for m in raw if isinstance(m, (str, int, float))] if isinstance(raw, list) else []

    if not candidates:
        return VerifiabilityResult(
            checkable=False, matched_metrics=[], reason="expected_metric_improvementsが空(予測が示されていない)"
        )

    matched = [
        c for c in candidates
        if any(vocab in c.lower() or c.lower() in vocab for vocab in _MEASURABLE_METRIC_VOCABULARY)
    ]
    if not matched:
        return VerifiabilityResult(
            checkable=False,
            matched_metrics=[],
            reason=f"示された予測({', '.join(candidates)})が、既知の測定可能指標(RC-1〜5・"
            "Citation Precision・memory_precision等)のいずれとも一致しない",
        )

    return VerifiabilityResult(
        checkable=True, matched_metrics=matched, reason=f"既知の指標({', '.join(matched)})への具体的な予測を持つ"
    )


# 検証可能な指標が1つ一致するごとの加点。上限を設ける判断根拠: 依頼書が
# 求める「シンプルな基準」に沿い、指標を並べ立てるほど無制限にスコアが
# 伸びる設計を避けるため(D-1のbuild_metric_degradation_itemsが「同時
# 悪化2件以上でseverity=high、それ以上は区別しない」としたのと同じ、
# 上限を設けて過度な精緻化を避ける判断)。
_METRIC_SPECIFICITY_BONUS_PER_METRIC = 1
_METRIC_SPECIFICITY_BONUS_CAP = 3


def compute_priority_score(hypothesis: dict[str, Any], verifiability: VerifiabilityResult) -> int:
    """D-1由来のevidence_priority_score(複数指標への同時悪化度等、既に
    D-1で確立済みの優先度)と、D-2由来の仮説の質(検証可能な指標をどれだけ
    具体的に挙げられたか)を単純加算する。

    判断根拠(単純加算にした理由): 依頼書「D-1由来の優先順位付けと、D-2で
    追加された仮説の質を、統合的に評価する」に対し、重み付け係数を新たに
    チューニングする複雑な式ではなく、両者をそのまま足し合わせる方式に
    した。D-1のevidence_priority_score自体が既に「深刻度+複数回記録
    ボーナス」のようなシンプルな加算で構成されており、その設計哲学を
    そのまま延長した。
    """
    evidence_score = hypothesis.get("evidence_priority_score")
    base = int(evidence_score) if isinstance(evidence_score, (int, float)) else 0
    specificity_bonus = min(
        len(verifiability.matched_metrics) * _METRIC_SPECIFICITY_BONUS_PER_METRIC,
        _METRIC_SPECIFICITY_BONUS_CAP,
    )
    return base + specificity_bonus


@dataclass
class RankedHypothesis:
    hypothesis_id: str | None
    track: str  # "normal" | "special_review"
    priority_rank: int | None  # Noneはspecial_review(競合ランキングの対象外)
    priority_score: int
    verifiability: VerifiabilityResult
    phase_e_handoff: dict[str, Any] | None
    raw: dict[str, Any] = field(default_factory=dict)


def build_phase_e_handoff(
    hypothesis: dict[str, Any], verifiability: VerifiabilityResult, *, priority_rank: int | None
) -> dict[str, Any]:
    """Phase Eへの引き渡し形式(データ構造)。依頼書3章「どの仮説を、
    どういう情報とともにPhase Eへ渡すべきか」への対応——本タスクでは実際の
    接続は行わないため、この関数はデータ構造を組み立てるだけで、どこにも
    送信・実行しない。

    設計方針(判断根拠): Phase E(自動テスト環境、未実装)が今後どのような
    形でこの仮説を「テスト可能な変更」へ具体化するかは、本タスクのスコープ
    外である。そのため、D-3側で断定できる情報(仮説の内容・根拠・優先度・
    検証可能性の判定)と、Phase E側が今後追加すべき情報(実際のテスト計画・
    ロールバック手順等)を、意図的に分離した形にした——後者は`None`や
    空のプレースホルダとして明示し、Phase E側が「ここを埋める」と一目で
    分かるようにしている。
    """
    return {
        "hypothesis_id": hypothesis.get("id"),
        "priority_rank": priority_rank,
        "title": hypothesis.get("title"),
        "what_is_problem": hypothesis.get("what_is_problem"),
        "why_problem": hypothesis.get("why_problem"),
        "how_to_improve": hypothesis.get("how_to_improve"),
        "source_evidence": {
            "category": hypothesis.get("source_evidence_category"),
            "title": hypothesis.get("source_evidence_title"),
            "priority_score": hypothesis.get("evidence_priority_score"),
        },
        "expected_metric_improvements": hypothesis.get("expected_metric_improvements") or [],
        "verifiable_metrics": verifiability.matched_metrics,
        "verifiability": {"checkable": verifiability.checkable, "reason": verifiability.reason},
        # Phase E(未実装)が埋めるべき項目。D-3はここに具体的な値を
        # 設定しない——テスト計画の設計自体がPhase Eのスコープであるため。
        "test_plan": None,
        "rollback_plan": None,
        "target_files": None,
    }


@dataclass
class PrioritizationResult:
    normal_track: list[RankedHypothesis]
    special_review_track: list[RankedHypothesis]


def prioritize_hypotheses(hypotheses: list[dict[str, Any]]) -> PrioritizationResult:
    """仮説群を、requires_special_reviewで2つのトラックへ完全に分離した
    上で、それぞれを優先順位付けする。

    判断根拠(2トラックを完全分離する理由、依頼書の要件2への対応):
    special_reviewトラックの仮説は、通常のpriority_scoreによる競合
    ランキングに一切参加させない——D-2のfinalize_hypothesis()が「通常の
    仮説より後ろに並べる」という単純な並べ替えで対応していたのに対し、
    D-3ではより明確に「別枠」として構造的に分離した(依頼書「常に別枠で、
    最も慎重に扱われるようにすること」という、D-2より一段階強い要求への
    対応)。special_reviewトラックにはpriority_rankを付与しない
    (None)——「ランキングの対象外」であることをデータ構造として明示する。

    normalトラックの並べ替え: 依頼書「曖昧で検証しようがない仮説は、
    優先順位を下げること」に対応するため、(a) 検証可能かどうかを最優先の
    軸、(b) priority_scoreを次点の軸、という二段階ソートにした——D-2の
    finalize_hypothesis()が確立した「フラグ有無を最優先、スコアを次点」
    という二段階ソートの設計をそのまま踏襲した(新しい重み付け式を作ら
    ない、という一貫した判断)。
    """
    normal: list[tuple[dict[str, Any], VerifiabilityResult, int]] = []
    special: list[tuple[dict[str, Any], VerifiabilityResult, int]] = []

    for hyp in hypotheses:
        verifiability = assess_verifiability(hyp)
        score = compute_priority_score(hyp, verifiability)
        if hyp.get("requires_special_review"):
            special.append((hyp, verifiability, score))
        else:
            normal.append((hyp, verifiability, score))

    # (not checkable, -score): 検証可能なものを先に、その中でscore降順。
    normal.sort(key=lambda entry: (not entry[1].checkable, -entry[2]))
    # special_reviewトラックも、目視確認の優先順位付けの参考になるよう
    # score降順で並べておくが、priority_rank自体は付与しない(ランキング
    # 対象外であることを明示するため)。
    special.sort(key=lambda entry: -entry[2])

    normal_ranked = [
        RankedHypothesis(
            hypothesis_id=hyp.get("id"),
            track="normal",
            priority_rank=rank,
            priority_score=score,
            verifiability=verifiability,
            phase_e_handoff=build_phase_e_handoff(hyp, verifiability, priority_rank=rank),
            raw=hyp,
        )
        for rank, (hyp, verifiability, score) in enumerate(normal, start=1)
    ]
    special_ranked = [
        RankedHypothesis(
            hypothesis_id=hyp.get("id"),
            track="special_review",
            priority_rank=None,
            priority_score=score,
            verifiability=verifiability,
            # special_reviewトラックはPhase Eへのhandoffペイロードを
            # 意図的に生成しない——人間の確認を経る前に、自動的にPhase E
            # へ流れうる形のデータを作らないための判断(依頼書「最も慎重に
            # 扱われるようにすること」への対応)。
            phase_e_handoff=None,
            raw=hyp,
        )
        for hyp, verifiability, score in special
    ]

    return PrioritizationResult(normal_track=normal_ranked, special_review_track=special_ranked)
