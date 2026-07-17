# 役割: Phase D-1「根拠収集」のオーケストレーション(DB・ファイルI/O)。
#
# evidence_aggregation.py(純粋関数)にデータを渡し、Phase R(RC指標)・
# Phase G(Grounding指標)・Phase S-2(Mastery Driveの言語化)・
# bug_inventory.md(過去のインシデント記録)という4つの既存資産から根拠を
# 集約する。cycle_health_runner.py/grounding_health_runner.pyと同じ役割
# 分担(計算ロジックとI/Oを分離)をそのまま踏襲した。
#
# 【重要】ここでは新しいデータ収集を一切行わない。既存のsigmaris_cycle_
# health_runs・sigmaris_grounding_health_runs・sigmaris_experience
# (category="proposal")・docs/sigmaris/bug_inventory.mdを、そのまま
# 読み取るだけ(依頼書の制約)。
#
# 永続化(sigmaris_evidence_bundlesへの書き込み)はこのモジュールの責務
# ではない — run_cycle_health.py/run_grounding_health.pyと同じ役割分担を
# 踏襲し、scripts/run_evidence_aggregation.py側で行う(--dry-run対応)。

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.cycle_health_runs_store import get_recent_cycle_health_runs
from app.services.evidence_aggregation import aggregate_evidence
from app.services.experience_layer import get_recent_experiences
from app.services.grounding_health_runs_store import get_recent_grounding_health_runs

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 20

# persona_loader.py::load_persona()と同じ「複数の候補パスを順に試す」
# 方式を踏襲(判断根拠: このファイルもdocs/配下の実運用ドキュメントを
# 実行時に読む、既に確立された前例があるパターン)。キャッシュは持たない
# ——本タスクの利用シーンは手動実行のオフラインCLIのみであり、persona_
# loader.pyのような会話ターン毎の高頻度呼び出しではないため、mtimeキャッ
# シュを追加する必要性が薄いと判断した。
def _find_bug_inventory_path() -> Path | None:
    candidates = [
        Path(__file__).resolve().parents[3] / "docs" / "sigmaris" / "bug_inventory.md",
        Path("/app/docs/sigmaris/bug_inventory.md"),
    ]
    return next((c for c in candidates if c.is_file()), None)


def _load_bug_inventory_markdown() -> str | None:
    path = _find_bug_inventory_path()
    if path is None:
        logger.warning("evidence_aggregation_runner: bug_inventory.md not found, skipping recurring_problem category")
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        logger.exception("evidence_aggregation_runner: failed to read bug_inventory.md")
        return None


async def run_evidence_aggregation(*, limit: int = _DEFAULT_LIMIT) -> dict[str, Any]:
    """根拠収集を1回分実行する。limitは各DBソース(RC指標・Grounding指標・
    Mastery提案)から遡って読む件数の上限——Phase R/Gの`window_days`
    (期間ベース)とは異なり、ここでは「直近何回分の実行/提案を根拠の母集団
    にするか」という件数ベースの指定にした。判断根拠: RC/Grounding指標は
    手動実行のCLIであり実行間隔が不定期なため、期間よりも「直近N回分」の
    方が意味のある母集団になる(cycle_health_runs_store.get_recent_
    cycle_health_runs()自体が既にlimitベースの設計であることとも整合)。
    """
    run_at = datetime.now(UTC)

    rc_runs = await get_recent_cycle_health_runs(limit=limit)
    grounding_runs = await get_recent_grounding_health_runs(limit=limit)
    mastery_experiences = await get_recent_experiences(
        limit=limit, experience_type="unresolved", category="proposal"
    )
    bug_inventory_markdown = _load_bug_inventory_markdown()

    bundle = aggregate_evidence(
        rc_runs=rc_runs,
        grounding_runs=grounding_runs,
        mastery_experiences=mastery_experiences,
        bug_inventory_markdown=bug_inventory_markdown,
    )

    items_payload = [asdict(item) for item in bundle.items]
    category_counts: dict[str, int] = {}
    for item in bundle.items:
        category_counts[item.category] = category_counts.get(item.category, 0) + 1

    return {
        "run_at": run_at.isoformat(),
        "limit": limit,
        "sources_checked": bundle.sources_checked,
        "category_counts": category_counts,
        "items": items_payload,
        "details_for_persistence": {
            "items": items_payload,
            "sources_checked": bundle.sources_checked,
        },
    }
