#!/usr/bin/env python3
"""
Phase E-4「マイグレーションレビュー待ちキュー」— E-1が"excluded_
migration"と判定した(DBスキーマ変更に言及する)仮説を、専用の人間
レビュー待ちキューへ記録する。

【最重要】本スクリプトは、マイグレーションを自動的に承認・適用する
仕組みではない。**新規に記録される行は、常にreview_status="pending"
であり、それ以外の状態(approved/rejected)は、人間が明示的に
`record_review_decision()`を呼ぶことでのみ変わる。** どのスクリプトも
自動的に承認・却下を行わない。

キューへ記録される情報(依頼書「人間が判断するために必要な情報」への
対応):
  - 仮説の内容(title・何が問題か・なぜ問題か・どう改善するか)
  - マイグレーションと判定された理由(E-1が検出したキーワード)
  - D-3の優先順位付け結果(priority_rank・priority_score)
  - 根拠となった元のD-1 evidence(source_evidence)
  - 期待される指標改善(expected_metric_improvements)

使い方:
    cd backend
    python scripts/run_migration_review_queue.py
    python scripts/run_migration_review_queue.py --limit 500
    python scripts/run_migration_review_queue.py --dry-run   # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_static_verifications/sigmaris_
    hypothesis_prioritiesの読み取り、およびsigmaris_migration_review_
    queueへの記録に必要)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.migration_review_queue_runner import build_migration_review_queue_batch  # noqa: E402
from app.services.migration_review_queue_store import record_migration_review_entries  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402


async def _main(args: argparse.Namespace) -> None:
    print(f"Phase E-4 マイグレーションレビュー待ちキューを更新中... limit={args.limit}")
    entries = await build_migration_review_queue_batch(limit=args.limit)

    print("\n" + "=" * 60)
    print("Phase E-4 マイグレーションレビュー待ちキュー")
    print("=" * 60)
    print(f"新規に検出された、未キュー登録の仮説: {len(entries)}件")
    print("(既にキューにある仮説は、重複して積まれません)")
    print()
    if not entries:
        print("(新規のマイグレーション言及仮説は見つかりませんでした)")
    for e in entries:
        print(f"- {e.title}")
        print(f"    D-3優先順位: rank={e.d3_priority_rank}, score={e.d3_priority_score}")
        print(f"    マイグレーション判定理由: {e.migration_reason}")
        print(f"    何が問題か: {e.what_is_problem}")
        print(f"    どう改善するか: {e.how_to_improve}")
        print(f"    レビュー状態: {e.review_status}(人間の判断待ち)")
    print("=" * 60)

    if args.dry_run:
        print("\n--dry-run のため sigmaris_migration_review_queue には記録していません。")
        return

    ids = await record_migration_review_entries(entries)
    if ids or not entries:
        print(f"\n✓ sigmaris_migration_review_queue に{len(ids)}件記録しました(review_status=pending)")
    else:
        print(
            "\n⚠ sigmaris_migration_review_queue への記録に失敗しました "
            "(マイグレーション202607300057未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記の一覧自体は正しく計算されています。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--limit", type=int, default=200, help="E-1/D-3の記録を遡って探す件数上限(デフォルト200)"
    )
    parser.add_argument("--dry-run", action="store_true", help="DBに記録せず標準出力のみ行う")
    args = parser.parse_args()

    async def run() -> None:
        try:
            await _main(args)
        finally:
            await shutdown_supabase_http_client()

    asyncio.run(run())


if __name__ == "__main__":
    main()
