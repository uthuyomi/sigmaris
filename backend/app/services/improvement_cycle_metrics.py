# 役割: Phase D〜H(自己改良システム、未実装)向け、SB-7
# (improvement_cycle_gain)の純粋な算出ロジック。
#
# 【重要】Phase D〜Hはまだ存在しない(docs/sigmaris/sigmaris_roadmap.md
# 「Phase D〜H: 自己改良システム本体」参照)。このモジュールを実際に
# 「変更前→変更後」のサイクルとして呼び出す実装は本タスク(Phase
# C-full-2)の範囲外であり、意図的に行っていない。ここにあるのは、
# Phase Dの改良提案エンジンが実装された時点ですぐ使える、指標スナップ
# ショット2つ(before/after)を単一の「伸び率」に集約するための計算
# ロジックのみ。eval_metrics.py(Phase C-mini/SB-3)と同じく、I/Oを
# 一切持たない純粋関数のみを置く。DB呼び出しはimprovement_cycle_
# store.py側の責務。

from __future__ import annotations

from dataclasses import dataclass, field

# 指標ごとに「値が大きいほど良い」か「値が小さいほど良い」かが異なるため、
# 一律に (after - before) / before では符号を誤る(例: response_error_rate
# が下がった=改善なのに、単純な差分だと負の値になり「悪化」に見えてしまう)。
# ここで向きを明示的に管理し、常に「正の値=改善」に正規化してから平均する。
_HIGHER_IS_BETTER = frozenset({
    "memory_f1_score",       # SB-1
    "rag_ndcg_score",        # SB-2
    "curiosity_relevance_score",  # SB-5(将来、対象機能実装後)
    "self_diagnosis_accuracy",    # SB-6(将来、対象機能実装後)
})
_LOWER_IS_BETTER = frozenset({
    "response_error_rate",     # SB-4
    "memory_duplicate_rate",   # SB-3(Phase C-full-2)
})
_KNOWN_METRICS = _HIGHER_IS_BETTER | _LOWER_IS_BETTER


@dataclass
class MetricGain:
    metric: str
    before: float
    after: float
    pct_change: float  # 常に「正の値=改善」の向きに正規化済み


@dataclass
class ImprovementCycleGain:
    overall_gain_pct: float
    metric_gains: list[MetricGain] = field(default_factory=list)
    skipped_metrics: list[str] = field(default_factory=list)  # 算出できなかった指標名+理由


def compute_improvement_cycle_gain(
    before: dict[str, float | None],
    after: dict[str, float | None],
) -> ImprovementCycleGain:
    """SB-7 (improvement_cycle_gain) の算出。

    before/afterは、SB-1〜SB-6のうち計測済みの指標名をキーとする辞書
    (例: {"memory_f1_score": 0.72, "response_error_rate": 0.02, ...})。
    両方に同じキーが存在し、値がNoneでなく、向きが既知
    (_HIGHER_IS_BETTER/_LOWER_IS_BETTERのいずれか)で、beforeの値が0でない
    指標のみを対象にする。

    算出式: 指標ごとに「正の値=改善」となるよう正規化したパーセント変化
    (higher-is-better: (after-before)/before、lower-is-better:
    (before-after)/before)を求め、**対象となった指標群の単純平均**を
    overall_gain_pctとする。判断根拠: SB-1〜SB-6は単位・スケールが
    バラバラ(0〜1のスコアと、0〜1の比率が混在)なため、いずれもパーセント
    変化という無次元量に揃えた上で平均するのが最も単純で説明しやすい。
    どの指標を重視するかという重み付けは、実際に改善サイクルが動き出し
    (Phase D以降)、どの指標がグッドハート化しやすいか等の知見が蓄積して
    から検討すべきであり、現時点で恣意的な重みを入れないことを優先した
    (単純平均=暫定的に「指標ごとに等しく重要」という前提)。
    """
    metric_gains: list[MetricGain] = []
    skipped: list[str] = []

    all_keys = set(before) | set(after)
    for metric in sorted(all_keys):
        before_value = before.get(metric)
        after_value = after.get(metric)

        if metric not in _KNOWN_METRICS:
            skipped.append(f"{metric} (向きが未登録)")
            continue
        if before_value is None or after_value is None:
            skipped.append(f"{metric} (before/afterのいずれかが欠損)")
            continue
        if before_value == 0:
            skipped.append(f"{metric} (beforeが0のため変化率を計算できない)")
            continue

        if metric in _HIGHER_IS_BETTER:
            pct_change = (after_value - before_value) / before_value
        else:
            pct_change = (before_value - after_value) / before_value

        metric_gains.append(
            MetricGain(metric=metric, before=before_value, after=after_value, pct_change=pct_change)
        )

    overall_gain_pct = (
        sum(g.pct_change for g in metric_gains) / len(metric_gains) if metric_gains else 0.0
    )

    return ImprovementCycleGain(
        overall_gain_pct=overall_gain_pct,
        metric_gains=metric_gains,
        skipped_metrics=skipped,
    )
