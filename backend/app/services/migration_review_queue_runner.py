# 役割: Phase E-4「マイグレーションレビュー待ちキュー」のオーケストレー
# ション(DB I/O)。migration_review_queue.py(純粋関数)にデータを渡し、
# E-1(sigmaris_static_verifications)・D-3(sigmaris_hypothesis_
# priorities)を突き合わせて、新規のレビューエントリを組み立てる。
#
# 永続化(sigmaris_migration_review_queueへの書き込み)はこのモジュールの
# 責務ではない——既存の全Runnerと同じ役割分担を踏襲し、scripts/run_
# migration_review_queue.py側で行う(--dry-run対応)。

from __future__ import annotations

import asyncio

from app.services.hypothesis_prioritization_store import get_recent_prioritization_run
from app.services.migration_review_queue import MigrationReviewEntry, select_new_migration_entries
from app.services.migration_review_queue_store import get_queued_hypothesis_ids
from app.services.static_verification_store import get_recent_static_verifications

_DEFAULT_LIMIT = 200


async def build_migration_review_queue_batch(*, limit: int = _DEFAULT_LIMIT) -> list[MigrationReviewEntry]:
    """E-1の直近の実行群から"excluded_migration"判定を集め、D-3の優先
    順位付け結果と突き合わせて、まだキューに無い仮説だけを、新規の
    レビューエントリとして組み立てる。

    limitは「直近何件のE-1/D-3記録まで遡って探すか」の上限——E-1/D-3
    いずれも追記専用ログであり、際限なく全件を毎回読み直すのは非効率
    なため、他のRunnerと同じ「寛容だが上限のある」慣習を踏襲した。
    """
    static_rows, priority_rows, already_queued = await asyncio.gather(
        get_recent_static_verifications(limit=limit),
        get_recent_prioritization_run(limit=limit),
        get_queued_hypothesis_ids(),
    )
    return select_new_migration_entries(static_rows, priority_rows, already_queued_hypothesis_ids=already_queued)
