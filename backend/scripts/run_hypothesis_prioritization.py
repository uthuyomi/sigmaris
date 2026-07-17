#!/usr/bin/env python3
"""
Phase D-3「優先順位付け・検証可能性の評価」— 改良提案エンジン(Phase D)の
仕上げ。D-2が生成した仮説一覧(sigmaris_hypotheses)を、以下の2トラックへ
分離し、それぞれを評価する。

  normalトラック         requires_special_review=Falseの仮説。
                         (a) 検証可能性(expected_metric_improvementsが
                         既知の測定可能指標を具体的に指しているか)、
                         (b) 優先度スコア(D-1由来のevidence_priority_score
                         + D-2由来の指標具体性ボーナス)
                         の二段階ソートで並べ替える。検証不能な仮説は、
                         スコアに関わらず必ず後方に配置される。
  special_reviewトラック requires_special_review=Trueの仮説。通常の
                         優先順位付けには一切参加させず、別枠で保持する。
                         Phase Eへのhandoffペイロードも生成しない
                         (人間の確認を経る前に自動で下流へ流れる形の
                         データを作らないため)。

normalトラックの各仮説には、Phase E(自動テスト環境、未実装)への
引き渡し形式(データ構造)を組み立てて添付する。**本タスクでは、実際に
Phase Eへ接続する処理は一切行わない**——このスクリプトはデータ構造の
設計と、DBへの記録までを行う。

使い方:
    cd backend
    python scripts/run_hypothesis_prioritization.py
    python scripts/run_hypothesis_prioritization.py --limit 100
    python scripts/run_hypothesis_prioritization.py --dry-run   # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_hypothesesの読み取り、および
    sigmaris_hypothesis_prioritiesへの記録に必要)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.hypothesis_prioritization_runner import run_hypothesis_prioritization  # noqa: E402
from app.services.hypothesis_prioritization_store import record_prioritization_run  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402


async def _main(args: argparse.Namespace) -> None:
    print(f"Phase D-3 優先順位付け・検証可能性評価を実行中... limit={args.limit}")
    result = await run_hypothesis_prioritization(limit=args.limit)
    run_at = datetime.now(UTC).isoformat()

    print("\n" + "=" * 60)
    print("Phase D-3 優先順位付け・検証可能性評価(Phase Dの仕上げ)")
    print("=" * 60)
    print(f"評価対象の仮説件数        : {result['hypotheses_considered']}")
    print(f"normalトラック件数        : {result['normal_track_count']}")
    print(f"  うち検証可能な件数      : {result['normal_track_checkable_count']}")
    print(f"special_reviewトラック件数: {result['special_review_track_count']}")
    print()

    print("--- normalトラック(優先順位順、検証不能な仮説は後方に配置) ---")
    if not result["normal_track"]:
        print("(0件——D-2が未実行、または全ての仮説がrequires_special_review)")
    for r in result["normal_track"]:
        raw = r["raw"]
        checkable_mark = "✓検証可能" if r["verifiability"]["checkable"] else "✗検証不能"
        print(f"[#{r['priority_rank']}] score={r['priority_score']} {checkable_mark}  {raw.get('title')}")
        print(f"    検証可能性: {r['verifiability']['reason']}")
    print()

    print("--- special_reviewトラック(別枠管理、ランキング対象外) ---")
    if not result["special_review_track"]:
        print("(0件)")
    for r in result["special_review_track"]:
        raw = r["raw"]
        print(f"[要レビュー] score={r['priority_score']}(参考値、ランキングには使わない)  {raw.get('title')}")
        print(f"    理由: {raw.get('safety_review_reason')}")
    print("=" * 60)

    if args.dry_run:
        print("\n--dry-run のため sigmaris_hypothesis_priorities には記録していません。")
        return

    ids = await record_prioritization_run(
        run_at=run_at, normal_track=result["normal_track"], special_review_track=result["special_review_track"]
    )
    total = result["normal_track_count"] + result["special_review_track_count"]
    if ids or total == 0:
        print(f"\n✓ sigmaris_hypothesis_priorities に{len(ids)}件記録しました")
    else:
        print(
            "\n⚠ sigmaris_hypothesis_priorities への記録に失敗しました "
            "(マイグレーション202607270054未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記の評価結果自体は正しく計算されています。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--limit", type=int, default=50, help="評価対象とする直近の仮説件数上限(デフォルト50)"
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
