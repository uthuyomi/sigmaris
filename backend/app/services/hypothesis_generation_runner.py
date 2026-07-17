# 役割: Phase D-2「仮説生成」のオーケストレーション(DB I/O + LLM呼び出し
# の並び)。hypothesis_generation.py(生成・フィルタ・検証・Constitution
# 連携)へデータを渡し、D-1が最後に記録した根拠一覧(sigmaris_evidence_
# bundles)から、優先度の高い根拠を対象に仮説を組み立てる。
#
# evidence_aggregation_runner.py/grounding_health_runner.pyと同じ役割分担
# (計算・生成ロジックとI/Oを分離)を踏襲した。
#
# 永続化(sigmaris_hypothesesへの書き込み)はこのモジュールの責務ではない
# — 既存の全Runnerと同じ役割分担を踏襲し、scripts/run_hypothesis_
# generation.py側で行う(--dry-run対応)。

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from app.services.evidence_aggregation import EvidenceItem
from app.services.evidence_aggregation_store import get_recent_evidence_bundles
from app.services.hypothesis_generation import (
    critique_hypothesis_correspondence,
    finalize_hypothesis,
    generate_hypothesis,
    is_vague_or_unsupported,
)

logger = logging.getLogger(__name__)

_DEFAULT_TOP_N_ITEMS = 5


def _item_from_dict(raw: dict[str, Any]) -> EvidenceItem | None:
    """sigmaris_evidence_bundles.itemsのjsonb1件を、evidence_aggregation.
    EvidenceItemへ復元する。D-1が書き込んだasdict(EvidenceItem)と同じ
    形状であることを前提とする——不正な形の場合はNone(fail-open)。"""
    try:
        return EvidenceItem(
            category=str(raw["category"]),
            source_system=str(raw["source_system"]),
            title=str(raw["title"]),
            description=str(raw.get("description") or ""),
            severity=raw.get("severity"),
            priority_score=int(raw.get("priority_score") or 0),
            details=raw.get("details") if isinstance(raw.get("details"), dict) else {},
        )
    except (KeyError, TypeError, ValueError):
        logger.warning("hypothesis_generation_runner: skipping malformed evidence item")
        return None


async def run_hypothesis_generation(*, top_n_items: int = _DEFAULT_TOP_N_ITEMS) -> dict[str, Any]:
    """直近1回分のevidence bundleから、優先度上位top_n_items件の根拠に
    対して仮説生成を試みる。D-1のitemsは既にpriority_score降順で保存
    されているため、上位N件をそのまま取ればよい(新しい優先順位付け
    ロジックは追加しない)。

    evidence bundleが1件も無い(D-1が未実行、またはマイグレーション未
    適用)場合は、空の結果を返す(fail-open、例外は投げない)。
    """
    bundles = await get_recent_evidence_bundles(limit=1)
    if not bundles:
        return {
            "evidence_bundle_id": None,
            "evidence_bundle_run_at": None,
            "candidates_considered": 0,
            "generated_count": 0,
            "filtered_vague_count": 0,
            "filtered_ungrounded_count": 0,
            "flagged_for_review_count": 0,
            "kept_count": 0,
            "hypotheses": [],
        }

    bundle = bundles[0]
    raw_items = bundle.get("items") if isinstance(bundle.get("items"), list) else []
    candidates = [item for item in (_item_from_dict(r) for r in raw_items[:top_n_items]) if item is not None]

    generated_count = 0
    filtered_vague_count = 0
    filtered_ungrounded_count = 0
    flagged_count = 0
    hypotheses: list[dict[str, Any]] = []

    for item in candidates:
        generated = await generate_hypothesis(item)
        if generated is None:
            continue
        generated_count += 1

        is_vague, _vague_reason = is_vague_or_unsupported(generated, item)
        if is_vague:
            filtered_vague_count += 1
            continue

        grounded, critique_reason = await critique_hypothesis_correspondence(generated, item)
        if not grounded:
            filtered_ungrounded_count += 1
            continue

        final = finalize_hypothesis(generated, item, grounded=grounded, critique_reason=critique_reason)
        if final is None:
            filtered_ungrounded_count += 1
            continue

        if final.requires_special_review:
            flagged_count += 1
        hypotheses.append(asdict(final))

    # 「フラグが立った仮説は、通常の仮説より優先順位を下げる」(依頼書)を、
    # 複雑な重み付け式ではなく「非フラグ群を先に、フラグ群を後に」という
    # 単純な並べ替えで満たす——D-1のaggregate_evidence()が確立した
    # 「シンプルな基準にとどめる」という判断をそのまま踏襲した。各グループ
    # 内はevidence_priority_score降順を維持する(既に候補選定時点で
    # 降順だったため、安定ソートでそのまま保たれる)。
    hypotheses.sort(key=lambda h: h["requires_special_review"])

    return {
        "evidence_bundle_id": bundle.get("id"),
        "evidence_bundle_run_at": bundle.get("run_at"),
        "candidates_considered": len(candidates),
        "generated_count": generated_count,
        "filtered_vague_count": filtered_vague_count,
        "filtered_ungrounded_count": filtered_ungrounded_count,
        "flagged_for_review_count": flagged_count,
        "kept_count": len(hypotheses),
        "hypotheses": hypotheses,
    }
