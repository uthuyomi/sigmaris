#!/usr/bin/env python3
"""
Phase F-1「仮説からコード差分への変換」— D-3で優先順位付けされ、E-1で
"baseline_healthy_with_coverage"(既存テストのカバレッジがある)と判定
された仮説から、LLM(advanced tier)に統一diff形式のコード差分を生成
させ、機械的な安全性チェックを経て、"承認待ち"としてDBへ保存する。

【絶対原則、繰り返し明記する】
本スクリプトは、生成した差分を、いかなる形でもGitへコミット・ブランチ
作成・プルリクエスト化しない。`git`コマンド・GitHub API呼び出しは、この
スクリプト、およびそれが呼び出すいずれのモジュールにも一切存在しない。
生成された差分は、常に`sigmaris_code_diff_proposals`テーブルへ、
review_status="pending"(安全性チェックを通過した場合)、または
"rejected"(通過しなかった場合、生成そのものが破棄され記録のみ残る)
として保存されるだけである。**承認された差分を実際に適用する仕組みは、
本タスクには一切存在しない**(将来のF-3で、慎重に設計される)。

対象仮説の絞り込み(要件2・3への対応、Phase F-2でE-1・E-2の統合により
2段階のTierへ拡張済み——hypothesis_verification.py参照):
  - Tier1: E-1のverdict="baseline_healthy_with_coverage"
    (既存テストのカバレッジが、仮説の内容に基づいて確認済み)
  - Tier2: E-1のverdict="insufficient_signal"だが、直近のE-2実行で
    サンドボックス基盤自体は健全と確認済み(**仮説の内容そのものが
    検証されたわけではない**、環境の可用性のみの確認であることに注意)
  - excluded_migration・baseline_unhealthyは、いずれのTierにも該当せず
    対象外
  - D-3のnormalトラック経由の仮説のみ(requires_special_reviewは
    構造的に除外済み)
  - E-4のmigration_review_queueに既に登録されている仮説は、防御的に
    再除外する

対象ファイルの絞り込み(要件、方針1):
  - D-3のtarget_files(常にNone、既知の限界)の代わりに、E-1の
    matched_modules(推定され、かつ既存テストのカバレッジと一致
    確認済みのモジュール名)を、対象ファイルの根拠として採用した
    (判断根拠、docs/sigmaris/phase_f_report.md参照)
  - 1つの仮説につき、1つの対象ファイルのみ

使い方:
    cd backend
    python scripts/run_code_diff_generation.py
    python scripts/run_code_diff_generation.py --limit 5
    python scripts/run_code_diff_generation.py --dry-run   # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_static_verifications/sigmaris_
    hypothesis_priorities/sigmaris_migration_review_queueの読み取り、
    およびsigmaris_code_diff_proposalsへの記録に必要)
    OPENAI_API_KEY (CODE_DIFF_GENERATIONの実行に必要)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.code_diff_generation_runner import run_code_diff_generation  # noqa: E402
from app.services.code_diff_proposal_store import record_diff_proposals  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402

_STATUS_LABELS = {
    "passed": "安全性チェック通過(承認待ち)",
    "blocked_sensitive_file": "却下(機密ファイル)",
    "blocked_safety_mechanism": "却下(安全機構ファイル)",
    "blocked_unexpected_target": "却下(意図しない対象ファイル)",
    "generation_failed": "生成失敗/対象外",
}

# Phase F-2: この提案が、E-1単独のカバレッジ確認によるものか、E-2の
# サンドボックス基盤の可用性のみによるものかを、CLI出力でも明確に区別
# する(後者は仮説の内容を検証したものではないため)。
_TIER_LABELS = {
    "hypothesis_verified_coverage": "Tier1: E-1が既存テストのカバレッジを確認済み",
    "sandbox_infra_available_unverified_content": "Tier2: E-2でサンドボックス基盤の可用性のみ確認済み(内容は未検証)",
}


async def _main(args: argparse.Namespace) -> None:
    print(f"Phase F-1 コード差分生成を実行中... limit={args.limit}")
    print("(生成された差分は、いかなる場合もコミット・PR化されません。承認待ちとして保存されるのみです)")
    result = await run_code_diff_generation(limit=args.limit)

    print("\n" + "=" * 60)
    print("Phase F-1 仮説からコード差分への変換(承認必須、コミットは行わない)")
    print("=" * 60)
    print(f"検討した候補仮説件数: {result['candidates_considered']}")
    for status, count in result["status_counts"].items():
        print(f"  {_STATUS_LABELS.get(status, status)}: {count}件")
    print()

    print("--- 個別結果 ---")
    if not result["proposals"]:
        print("(0件——E-1でbaseline_healthy_with_coverageと判定された仮説が無い可能性)")
    for p in result["proposals"]:
        label = _STATUS_LABELS.get(p["safety_check_status"], p["safety_check_status"])
        tier_label = _TIER_LABELS.get(p.get("verification_tier"), p.get("verification_tier"))
        print(f"[{label}] {p['title']} -> {p['target_file']}")
        print(f"    検証段階: {tier_label}")
        if p["safety_check_reason"]:
            print(f"    理由: {p['safety_check_reason']}")
        print(f"    review_status: {p['review_status']}")
    print("=" * 60)

    if args.dry_run:
        print("\n--dry-run のため sigmaris_code_diff_proposals には記録していません。")
        return

    ids = await record_diff_proposals(result["proposals"])
    if ids or not result["proposals"]:
        print(f"\n✓ sigmaris_code_diff_proposals に{len(ids)}件記録しました")
    else:
        print(
            "\n⚠ sigmaris_code_diff_proposals への記録に失敗しました "
            "(マイグレーション202607310058未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記の生成結果自体は正しく計算されています。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--limit", type=int, default=10, help="対象とする候補仮説件数の上限(デフォルト10)"
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
