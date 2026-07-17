#!/usr/bin/env python3
"""
Phase D-1「根拠収集」— 改良提案エンジン(Phase D)の第一段階。Phase R
(RC指標)・Phase G(Grounding継続測定)・Phase S-2(Mastery Driveの言語化)・
bug_inventory.md(過去のインシデント記録)という既存の4資産を、そのまま
読み取り・集約するだけの薄い層。

  measurement指標の悪化   RC-1〜4/Grounding指標が、過去の実行群の平均
                          から大きく落ち込んでいる場合に検出する
                          (search_trigger_rateは対象外——G-5報告書が
                          明記する通り方向性が不明な指標のため)
  繰り返し発生する問題     bug_inventory.mdの問題一覧表のうち、複数の
                          異なる報告書(.mdファイル)に渡って言及されて
                          いる、未解決の問題
  Mastery Driveの言語化   S-2が既に生成した改善提案(sigmaris_experience、
                          category="proposal")をそのまま取り込む

【重要】本スクリプトは根拠の収集・集約のみを行う。実際の改良案の生成
(仮説生成)は次タスク(D-2、未実装)のスコープであり、ここでは一切行わない。

使い方:
    cd backend
    python scripts/run_evidence_aggregation.py
    python scripts/run_evidence_aggregation.py --limit 50
    python scripts/run_evidence_aggregation.py --dry-run   # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_cycle_health_runs等の読み取り、
    およびsigmaris_evidence_bundlesへの記録に必要)

docs/sigmaris/bug_inventory.mdはファイルシステムから直接読む(DB経由では
ない)。リポジトリ直下のdocs/sigmaris/配下に存在しない場合、繰り返し問題
のカテゴリは0件のまま(警告ログのみ、スクリプト自体は失敗しない)。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.evidence_aggregation_runner import run_evidence_aggregation  # noqa: E402
from app.services.evidence_aggregation_store import record_evidence_bundle  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402

_CATEGORY_LABELS = {
    "metric_degradation": "測定指標の悪化",
    "recurring_problem": "繰り返し発生する問題",
    "mastery_proposal": "Mastery Driveの言語化内容",
}


async def _main(args: argparse.Namespace) -> None:
    print(f"Phase D-1 根拠収集を実行中... limit={args.limit}")
    result = await run_evidence_aggregation(limit=args.limit)

    print("\n" + "=" * 60)
    print("Phase D-1 根拠収集(改良提案エンジンの材料集約層)")
    print("=" * 60)
    print(f"実行時刻            : {result['run_at']}")
    sc = result["sources_checked"]
    print(f"確認したPhase R実行数 : {sc.get('phase_r_runs')}")
    print(f"確認したPhase G実行数 : {sc.get('phase_g_runs')}")
    print(f"確認したMastery提案数 : {sc.get('mastery_proposals')}")
    print(f"確認したbug_inventory行数: {sc.get('bug_inventory_rows')}")
    print()
    cc = result["category_counts"]
    for category, label in _CATEGORY_LABELS.items():
        print(f"[{label}] {cc.get(category, 0)}件")
    print()
    print("--- 根拠一覧(priority_score降順) ---")
    if not result["items"]:
        print("(根拠は0件——対象のDBテーブルが未作成、または悪化・繰り返し・")
        print(" 提案のいずれも現時点で検出されなかった可能性がある。0件は")
        print(" 「問題なし」を意味するとは限らない点に注意)")
    for item in result["items"]:
        label = _CATEGORY_LABELS.get(item["category"], item["category"])
        print(f"- [{label}/{item['severity']}/score={item['priority_score']}] {item['title']}")
    print("=" * 60)

    if args.dry_run:
        print("\n--dry-run のため sigmaris_evidence_bundles には記録していません。")
        return

    bundle_id = await record_evidence_bundle(
        run_at=result["run_at"],
        limit=result["limit"],
        sources_checked=result["sources_checked"],
        category_counts=result["category_counts"],
        items=result["details_for_persistence"]["items"],
        notes=args.notes,
    )
    if bundle_id:
        print(f"\n✓ sigmaris_evidence_bundles に記録しました (id={bundle_id})")
    else:
        print(
            "\n⚠ sigmaris_evidence_bundles への記録に失敗しました "
            "(マイグレーション202607250052未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記の集約結果自体は正しく計算されています。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--limit", type=int, default=20, help="各DBソースから遡って読む実行/提案の件数上限(デフォルト20)"
    )
    parser.add_argument("--notes", default=None, help="この実行に付けるメモ")
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
