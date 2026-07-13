# 役割: Phase R-2「循環健全性指標(RC)」のオーケストレーション(DB I/O)。
#
# cycle_health_metrics.py(純粋関数)にデータを渡し、RC-1(Cycle
# Completion Rate)・RC-2(Temporal Consistency Score)を算出する。
# eval_runner.py(C-mini/C-full)と同じ役割分担 — 計算ロジックとI/Oを
# 分離する。C-mini/C-fullとは別系統の指標であり、sigmaris_eval_runsとは
# 混在させない(docs/sigmaris/phase_r_report.md参照)。

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.app_chat_data import list_chat_messages, list_chat_threads
from app.services.cycle_health_metrics import (
    check_chat_message_order,
    check_event_facts_against_experiences,
    classify_experience_reach,
    compute_temporal_consistency_score,
)
from app.services.cycle_trace import trace_memory_to_experience
from app.services.experience_layer import (
    _CONSOLIDATION_SCAN_WINDOW,
    _MIN_EXPERIENCES_FOR_CONSOLIDATION,
    get_experiences_since,
    get_recent_experiences,
)
from app.services.user_fact_data import get_fact_items

logger = logging.getLogger(__name__)

# episode_consolidateジョブの予定実行時刻(proactive/scheduler.pyの
# CronTrigger(day_of_week="sun", hour=4, minute=55, timezone=tz)と一致
# させること)。scheduler.py側のスケジュールが変更された場合はここも
# 追随させる必要がある、既知のマジックナンバー同期(レポートの申し送り
# 事項に記載)。
_CONSOLIDATION_WEEKDAY = 6  # Python: Monday=0 ... Sunday=6
_CONSOLIDATION_HOUR = 4
_CONSOLIDATION_MINUTE = 55

# RC-2のchat_messages順序チェック対象にするスレッド数の上限。単一
# テナント運用でも数百スレッド蓄積する可能性はあるため、C-mini系の
# 「潔く上限を切って安全側に倒す」慣習(decision_log.py's
# _ADOPTION_RECOMPUTE_DECISION_LIMIT等)を踏襲。
_DEFAULT_CHAT_THREAD_LIMIT = 200


def _last_scheduled_consolidation_at(now: datetime, tz_name: str) -> datetime:
    """直近の(nowより過去または同時刻の)episode_consolidateジョブの
    予定実行時刻をUTC awareで返す。"""
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz)
    days_since = (local_now.weekday() - _CONSOLIDATION_WEEKDAY) % 7
    candidate = (local_now - timedelta(days=days_since)).replace(
        hour=_CONSOLIDATION_HOUR, minute=_CONSOLIDATION_MINUTE, second=0, microsecond=0
    )
    if candidate > local_now:
        candidate -= timedelta(days=7)
    return candidate.astimezone(UTC)


async def _fetch_thread_messages(jwt: str, thread_id: str) -> tuple[str, list[dict[str, Any]]]:
    messages = await list_chat_messages(jwt, thread_id=thread_id)
    return thread_id, messages


async def run_cycle_health(
    *,
    jwt: str,
    window_days: int = 30,
    chat_thread_limit: int = _DEFAULT_CHAT_THREAD_LIMIT,
) -> dict[str, Any]:
    """RC-1・RC-2を実際に計測する。C-mini(run_eval)と同様、jwtは対象
    ユーザーのもの(この環境は実質シングルユーザー運用 — 複数ユーザー化
    する場合はC-miniと同じくuser_idスコープへの拡張が必要、
    phase_c_mini_report.md 8章2項参照)。"""
    now = datetime.now(UTC)
    since = now - timedelta(days=window_days)
    since_iso = since.isoformat()

    # RC-1に必要なデータ: 期間内experience、現在アクティブな全fact
    # (source_experience_idsを見るために期間で絞らない — 古いfactが
    # 期間内のexperienceを参照していることもありうるため)。
    experiences, active_facts, pool_probe = await asyncio.gather(
        get_experiences_since(since_iso),
        get_fact_items(jwt, active_only=True),
        get_recent_experiences(limit=_MIN_EXPERIENCES_FOR_CONSOLIDATION),
    )

    reached_experience_ids: set[str] = set()
    for fact in active_facts:
        source_ids = fact.get("source_experience_ids")
        if isinstance(source_ids, list):
            reached_experience_ids.update(sid for sid in source_ids if isinstance(sid, str))

    last_consolidation_at = _last_scheduled_consolidation_at(now, settings.sigmaris_timezone)

    rc1 = classify_experience_reach(
        experiences,
        reached_experience_ids=reached_experience_ids,
        last_scheduled_consolidation_at=last_consolidation_at,
        total_experience_pool_size=len(pool_probe),
        min_experiences_for_consolidation=_MIN_EXPERIENCES_FOR_CONSOLIDATION,
        consolidation_scan_window=_CONSOLIDATION_SCAN_WINDOW,
    )

    # RC-2a: chat_messagesの並び順チェック。期間内に更新のあったスレッド
    # のみを対象にする(全スレッド走査は単一テナントでも際限なく増える
    # ため)。
    threads = await list_chat_threads(jwt)
    target_thread_ids = [
        t["id"]
        for t in threads
        if isinstance(t.get("id"), str)
        and isinstance(t.get("updated_at"), str)
        and t["updated_at"] >= since_iso
    ][:chat_thread_limit]

    thread_message_pairs = await asyncio.gather(
        *(_fetch_thread_messages(jwt, tid) for tid in target_thread_ids)
    )
    threads_by_id = {tid: messages for tid, messages in thread_message_pairs}
    chat_order_result = check_chat_message_order(threads_by_id)

    # RC-2b: event種別 + 統合由来(source_experience_ids)のfactのみ対象。
    # 直接会話由来のevent factはレースコンディションの対象になりうる
    # ため対象外(cycle_health_metrics.check_event_facts_against_
    # experiences()のdocstring参照)。
    event_facts = [
        f for f in active_facts
        if f.get("memory_kind") == "event"
        and isinstance(f.get("source_experience_ids"), list)
        and f.get("source_experience_ids")
    ]
    traced = await asyncio.gather(*(trace_memory_to_experience(f) for f in event_facts))
    event_fact_pairs = [
        (fact, trace_result.get("source_experiences", []))
        for fact, trace_result in zip(event_facts, traced, strict=True)
    ]
    event_violations = check_event_facts_against_experiences(event_fact_pairs)

    rc2 = compute_temporal_consistency_score(
        chat_order=chat_order_result,
        event_experience_checked=len(event_facts),
        event_experience_violations=event_violations,
        period_from=since_iso,
        period_to=now.isoformat(),
    )

    return {
        "run_at": now.isoformat(),
        "window_days": window_days,
        "rc1_cycle_completion": {
            "total_experiences": rc1.total_experiences,
            "reached_count": rc1.reached_count,
            "raw_completion_rate": rc1.raw_completion_rate,
            "eligible_count": rc1.eligible_count,
            "eligible_completion_rate": rc1.eligible_completion_rate,
            "reason_counts": rc1.reason_counts,
            "last_scheduled_consolidation_at": last_consolidation_at.isoformat(),
        },
        "rc2_temporal_consistency": {
            "score": rc2.score,
            "period_from": rc2.period_from,
            "period_to": rc2.period_to,
            "chat_threads_checked": chat_order_result.threads_checked,
            "chat_pairs_checked": chat_order_result.pairs_checked,
            "chat_order_violations": [asdict(v) for v in chat_order_result.violations],
            "chat_collapsed_timestamp_ratio": chat_order_result.collapsed_timestamp_ratio,
            "event_experience_checked": rc2.event_experience_checked,
            "event_experience_violations": [asdict(v) for v in rc2.event_experience_violations],
        },
    }
