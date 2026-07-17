# 役割: 「循環健全性指標(RC)」のオーケストレーション(DB I/O)。
#
# cycle_health_metrics.py(純粋関数)にデータを渡し、RC-1〜RC-5(Cycle
# Completion Rate・Temporal Consistency Score・Belief Stability Index・
# Policy-Belief Alignment・Cycle Break Detection)を算出する。
# eval_runner.py(C-mini/C-full)と同じ役割分担 — 計算ロジックとI/Oを
# 分離する。C-mini/C-fullとは別系統の指標であり、sigmaris_eval_runsとは
# 混在させない(docs/sigmaris/phase_r_report.md参照)。
#
# 永続化(sigmaris_cycle_health_runsへの書き込み)はこのモジュールの責務
# ではない — run_eval.py/eval_runner.pyの役割分担(runnerは計測のみ、
# 書き込みはCLIスクリプト側)をそのまま踏襲し、scripts/run_cycle_health.py
# が返り値のdetails_for_persistenceを使って書き込む。ただし、RC-3(前回
# スナップショットとの比較)・RC-5(過去値との比較)は計測そのものに
# 過去の実行結果が必要なため、*読み取り*はこのモジュール内で行う。
#
# 【Safety-3追記(docs/sigmaris/safety_governance_report.md)】RC-1〜5とは
# 別系統の観点として、safety_critical_files.pyへの登録漏れスキャン
# (safety_critical_files_scan.py)を、同じ測定基盤(定期実行・記録
# テーブル)に統合した。安全機構の追加登録漏れという「コード統治」の
# 懸念を、RC指標(循環そのものの健全性)と同じ枠組みで扱うことで、
# 新しい定期実行の仕組みをゼロから作らずに済ませている。

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.services.app_chat_data import list_chat_messages, list_chat_threads
from app.services.cycle_health_metrics import (
    build_belief_snapshot,
    check_chat_message_order,
    check_event_facts_against_experiences,
    classify_experience_reach,
    compute_belief_stability,
    compute_policy_belief_alignment,
    compute_temporal_consistency_score,
    detect_cycle_break,
)
from app.services.cycle_health_runs_store import get_recent_cycle_health_runs
from app.services.cycle_trace import trace_memory_to_experience, trace_policy_to_evidence
from app.services.decision_log import get_active_preference_patterns
from app.services.experience_layer import (
    _CONSOLIDATION_SCAN_WINDOW,
    _MIN_EXPERIENCES_FOR_CONSOLIDATION,
    get_experiences_since,
    get_recent_experiences,
)
from app.services.safety_critical_files_scan import find_unregistered_gate_files
from app.services.user_fact_data import get_fact_items

# Safety-3(docs/sigmaris/safety_governance_report.md): cycle_health_
# runner.py -> app/services/ -> app/ -> backend/。find_unregistered_gate_
# files()は、backend/app/services・backend/scriptsを走査する(safety_
# critical_files_scan.pyのdocstring参照)。
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# goal_alignment.py exposes no public "all flags regardless of surface-
# cooldown" reader — get_active_goal_alignment_flags() intentionally
# filters by _SURFACE_COOLDOWN_DAYS (a response-injection concern RC-4 has
# no business inheriting). _get_all_flags_for_context() already does
# exactly what RC-4 needs (goal_alignment.py's own goal_reference-reuse
# dedup context uses it for the same reason). Reusing it directly, rather
# than adding a second near-identical public function, mirrors the same
# judgment call cycle_health_runner.py already made for experience_layer's
# _CONSOLIDATION_SCAN_WINDOW in Phase R-2.
from app.services.goal_alignment import _get_all_flags_for_context

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

    # 過去の実行群(RC-3のスナップショット比較 / RC-5のベースライン算出、
    # 両方が同じ読み取りを共有する)。書き込みはここでは行わない —
    # eval_runner.run_eval()がsigmaris_eval_runsへの書き込みをscripts/
    # run_eval.py側に委ねているのと同じ役割分担(--dry-run対応のため)。
    previous_runs = await get_recent_cycle_health_runs(limit=20)

    # RC-3: Belief Stability Index。limit=100は決定パターンのプロンプト
    # 注入用(get_active_preference_patterns(limit=5)、orchestrator/
    # service.py)とは別の、分析目的の生成的な多めの取得
    # (decision_log.get_decisions_by_ids等と同じ「内部分析は寛容な上限」
    # という慣習)。
    patterns = await get_active_preference_patterns(limit=100)
    previous_snapshot = None
    if previous_runs:
        prev_details = previous_runs[0].get("details")
        if isinstance(prev_details, dict):
            snapshot = prev_details.get("belief_snapshot")
            if isinstance(snapshot, dict):
                previous_snapshot = snapshot
    rc3 = compute_belief_stability(current_patterns=patterns, previous_snapshot=previous_snapshot)
    belief_snapshot_now = build_belief_snapshot(patterns)

    # RC-4: Policy-Belief Alignment。R-1のtrace_policy_to_evidence()を
    # そのまま再利用してevidence_refsをdecision_log由来のものに解決する
    # (要件2の直接対応)。
    flags = await _get_all_flags_for_context(limit=100)
    flag_traces = await asyncio.gather(
        *(trace_policy_to_evidence(f["id"]) for f in flags if isinstance(f.get("id"), str))
    )
    flags_with_evidence_decision_ids = [
        (flag, [d.get("id") for d in trace.get("evidence_decisions", []) if isinstance(d.get("id"), str)])
        for flag, trace in zip(
            (f for f in flags if isinstance(f.get("id"), str)), flag_traces, strict=True
        )
    ]
    rc4 = compute_policy_belief_alignment(
        flags_with_evidence_decision_ids=flags_with_evidence_decision_ids, patterns=patterns
    )

    # RC-5: Cycle Break Detection。RC-1/RC-2それぞれの過去値のみを見る
    # (要件3の通り、RC-3/RC-4は対象外 — 単一実行あたりのサンプル数が
    # 少なく、閾値ベースの単純比較では時期尚早と判断、レポート参照)。
    historical_rc1_rates = [
        row["rc1_eligible_completion_rate"]
        for row in previous_runs
        if isinstance(row.get("rc1_eligible_completion_rate"), (int, float))
    ]
    historical_rc2_scores = [
        row["rc2_score"] for row in previous_runs if isinstance(row.get("rc2_score"), (int, float))
    ]
    rc5 = detect_cycle_break(
        current_rc1_eligible_rate=rc1.eligible_completion_rate,
        current_rc2_score=rc2.score,
        historical_rc1_eligible_rates=historical_rc1_rates,
        historical_rc2_scores=historical_rc2_scores,
    )

    # Safety-3: 安全上重要なファイルの追加漏れスキャン(要件2、RC-5との
    # 統合)。RC-1〜5と違い、履歴データを必要としない瞬間的な構造チェック
    # のため、"insufficient_history"に相当する状態は存在しない
    # (判断根拠、docs/sigmaris/safety_governance_report.md参照——RC-5の
    # 「過去平均との比較」をそのまま流用すると、レジストリが大きくなる
    # ほど1件の未登録漏れが比率上希釈され検知しづらくなるため、瞬間的な
    # 現在値チェックを直接採用した)。
    safety_scan = find_unregistered_gate_files(_BACKEND_ROOT)
    safety_governance_status = "healthy" if safety_scan.coverage_complete else "gap_detected"

    return {
        "run_at": now.isoformat(),
        "window_days": window_days,
        "period_from": since_iso,
        "period_to": now.isoformat(),
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
            "chat_order_violation_count": len(chat_order_result.violations),
            "chat_order_violations": [asdict(v) for v in chat_order_result.violations],
            "chat_collapsed_timestamp_ratio": chat_order_result.collapsed_timestamp_ratio,
            "event_experience_checked": rc2.event_experience_checked,
            "event_experience_violation_count": len(rc2.event_experience_violations),
            "event_experience_violations": [asdict(v) for v in rc2.event_experience_violations],
        },
        "rc3_belief_stability": {
            "score": rc3.score,
            "comparable_pattern_count": rc3.comparable_pattern_count,
            "flip_count": len(rc3.flips),
            "unsupported_flip_count": rc3.unsupported_flip_count,
            "flips": [asdict(f) for f in rc3.flips],
            "has_previous_snapshot": previous_snapshot is not None,
        },
        "rc4_policy_belief_alignment": {
            "score": rc4.score,
            "flags_evaluated": rc4.flags_evaluated,
            "alignments": [asdict(a) for a in rc4.alignments],
        },
        "rc5_cycle_break": {
            "status": rc5.status,
            "broke_metrics": [c.metric for c in rc5.checks if c.broke_threshold],
            "checks": [asdict(c) for c in rc5.checks],
        },
        # Safety-3: RC指標(循環そのものの健全性)とは別系統の観点だが、
        # 同じ測定基盤(定期実行・記録テーブル)を共有する形で統合した
        # (要件3)。「安全上重要なファイルが、safety_critical_files.pyに
        # 追加登録されないまま放置されていないか」を、RC-1〜5と同じ
        # cadenceで確認できるようにする。
        "safety_governance": {
            "status": safety_governance_status,
            "scanned_file_count": safety_scan.scanned_file_count,
            "gate_pattern_file_count": safety_scan.gate_pattern_file_count,
            "unregistered_count": safety_scan.unregistered_count,
            "unregistered_files": [c.relative_path for c in safety_scan.unregistered_candidates],
        },
        # cycle_health_runs_store.record_cycle_health_run()のdetails引数に
        # そのまま渡すためのペイロード。belief_snapshotは次回実行のRC-3
        # previous_snapshotになる(7章参照)。
        "details_for_persistence": {
            "belief_snapshot": belief_snapshot_now,
            "rc1_reason_counts": rc1.reason_counts,
            "rc3_flips": [asdict(f) for f in rc3.flips],
            "rc4_alignments": [asdict(a) for a in rc4.alignments],
            "rc5_checks": [asdict(c) for c in rc5.checks],
            "safety_governance_unregistered_files": [
                {"path": c.relative_path, "reasons": c.reasons} for c in safety_scan.unregistered_candidates
            ],
        },
    }
