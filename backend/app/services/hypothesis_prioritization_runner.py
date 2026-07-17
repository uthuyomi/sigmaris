# 役割: Phase D-3「優先順位付け・検証可能性の評価」のオーケストレーション
# (DB I/O)。hypothesis_prioritization.py(純粋関数)にデータを渡し、
# D-2が保存した仮説一覧(sigmaris_hypotheses)を、優先順位付け済みの
# normalトラックと、別枠管理のspecial_reviewトラックへ分離する。
#
# evidence_aggregation_runner.py/hypothesis_generation_runner.pyと同じ
# 役割分担(計算ロジックとI/Oを分離)を踏襲した。
#
# 永続化(sigmaris_hypothesis_prioritiesへの書き込み)はこのモジュールの
# 責務ではない——既存の全Runnerと同じ役割分担を踏襲し、scripts/run_
# hypothesis_prioritization.py側で行う(--dry-run対応)。

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.services.hypothesis_prioritization import prioritize_hypotheses
from app.services.hypothesis_store import get_recent_hypotheses

_DEFAULT_LIMIT = 50


async def run_hypothesis_prioritization(*, limit: int = _DEFAULT_LIMIT) -> dict[str, Any]:
    """直近limit件の仮説(sigmaris_hypotheses、requires_special_reviewの
    絞り込みなし=両トラック取得)を対象に、優先順位付け・検証可能性評価を
    行う。仮説が1件も無い場合は空の結果を返す(fail-open)。"""
    hypotheses = await get_recent_hypotheses(limit=limit)

    result = prioritize_hypotheses(hypotheses)

    # asdict()はRankedHypothesis内のVerifiabilityResult(ネストされた
    # dataclass)も再帰的にdictへ変換する。
    normal_payload = [asdict(r) for r in result.normal_track]
    special_payload = [asdict(r) for r in result.special_review_track]

    checkable_count = sum(1 for r in result.normal_track if r.verifiability.checkable)

    return {
        "hypotheses_considered": len(hypotheses),
        "normal_track_count": len(normal_payload),
        "special_review_track_count": len(special_payload),
        "normal_track_checkable_count": checkable_count,
        "normal_track": normal_payload,
        "special_review_track": special_payload,
    }
