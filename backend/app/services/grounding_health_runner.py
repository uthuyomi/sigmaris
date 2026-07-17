# 役割: 「Phase G継続測定」のオーケストレーション(DB I/O)。
#
# grounding_health_metrics.py(純粋関数)にデータを渡し、Citation
# Precision・Search Trigger Rate・Contradiction Rateを算出する。
# cycle_health_runner.py(Phase R)と同じ役割分担 — 計算ロジックとI/Oを
# 分離する。
#
# 永続化(sigmaris_grounding_health_runsへの書き込み)はこのモジュールの
# 責務ではない — run_cycle_health.py/cycle_health_runner.pyの役割分担を
# そのまま踏襲し、scripts/run_grounding_health.pyが返り値の
# details_for_persistenceを使って書き込む。

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.app_chat_data import count_assistant_messages_since
from app.services.citation_audit import get_citation_audit_log_since
from app.services.grounding_health_metrics import (
    compute_citation_precision,
    compute_contradiction_rate,
    compute_search_trigger_rate,
)


async def run_grounding_health(*, jwt: str, window_days: int = 30) -> dict[str, Any]:
    """Phase G継続測定を1回分実行する。window_days日前から現在までを
    対象期間とする(cycle_health_runner.pyと同じ「直近N日」方式)。"""
    period_to = datetime.now(UTC)
    period_from = period_to - timedelta(days=window_days)
    since = period_from.isoformat()

    audit_rows = await get_citation_audit_log_since(since)
    total_turns = await count_assistant_messages_since(jwt, since)

    citation_precision = compute_citation_precision(audit_rows)
    search_trigger = compute_search_trigger_rate(audit_rows, total_turns=total_turns)
    contradiction = compute_contradiction_rate(audit_rows)

    return {
        "window_days": window_days,
        "period_from": period_from.isoformat(),
        "period_to": period_to.isoformat(),
        "citation_precision": asdict(citation_precision),
        "search_trigger_rate": asdict(search_trigger),
        "contradiction_rate": asdict(contradiction),
        "details_for_persistence": {
            "audit_row_count": len(audit_rows),
        },
    }
