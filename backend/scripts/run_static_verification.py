#!/usr/bin/env python3
"""
Phase E-1「静的検証パイプライン」— サンドボックス環境の第一段階
(docs/sigmaris/phase_e_report.md「選択肢A」)。D-3が優先順位付けした
仮説(sigmaris_hypothesis_priorities、track="normal"のみ)を対象に、
**実際にコードを一切変更せず**、以下の2つだけを行う。

  1. ベースライン確認   既存の(変更していない)backend/tests/を、
                        そのままsubprocessで実行し、現状で全て
                        通っていることを確認する
  2. カバレッジ照合     仮説の文面から推定される対象領域に、既存の
                        テストが存在するかを、import文の静的解析
                        (実行なし)で確認する

マイグレーション(DBスキーマ変更)に言及する仮説は、本パイプラインの
対象から常に除外される(docs/sigmaris/phase_e_report.md 3.2節の方針
通り、人間による手動レビューが必須のまま)。

【重要】判定は「合格/不合格」の二値ではなく、この手法で誠実に主張できる
範囲の3値(excluded_migration/baseline_unhealthy/insufficient_signal/
baseline_healthy_with_coverage)にとどめている。実際にコードを動かして
いない以上、「この仮説は正しい」ことは一切証明できない——あくまで
「実装前に、この領域には既存の回帰テストがあるか」という参考情報。

使い方:
    cd backend
    python scripts/run_static_verification.py
    python scripts/run_static_verification.py --limit 20
    python scripts/run_static_verification.py --dry-run   # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_hypothesis_prioritiesの読み取り、
    およびsigmaris_static_verificationsへの記録に必要)
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

from app.services.static_verification_runner import run_static_verification  # noqa: E402
from app.services.static_verification_store import record_static_verification_run  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402

_VERDICT_LABELS = {
    "excluded_migration": "除外(マイグレーション言及)",
    "baseline_unhealthy": "ベースライン不健全",
    "insufficient_signal": "検証不能(既存テストなし)",
    "baseline_healthy_with_coverage": "既存テストありで健全",
}


async def _main(args: argparse.Namespace) -> None:
    print(f"Phase E-1 静的検証パイプラインを実行中... limit={args.limit}")
    print("(既存のbackend/tests/をそのまま実行するのみ。コードの変更は一切行いません)")
    result = await run_static_verification(limit=args.limit)
    run_at = datetime.now(UTC).isoformat()

    baseline = result["baseline"]
    print("\n" + "=" * 60)
    print("Phase E-1 静的検証パイプライン(サンドボックス環境、第一段階)")
    print("=" * 60)
    print(f"ベースライン(backend/tests/): {'PASS' if baseline['passed'] else 'FAIL'}")
    print(f"  {baseline['summary']}")
    print()
    print(f"評価対象の仮説件数: {result['candidates_considered']}")
    for verdict, count in result["verdict_counts"].items():
        print(f"  {_VERDICT_LABELS.get(verdict, verdict)}: {count}件")
    print()

    print("--- 個別結果 ---")
    if not result["results"]:
        print("(0件——D-3が未実行、または優先順位付け結果にnormalトラックの仮説が無い)")
    for r in result["results"]:
        label = _VERDICT_LABELS.get(r["verdict"], r["verdict"])
        print(f"[{label}] hypothesis_id={r['hypothesis_id']}")
        print(f"    理由: {r['reason']}")
        if r["matched_modules"]:
            print(f"    対象領域と推定されたモジュール: {', '.join(r['matched_modules'])}")
    print("=" * 60)

    if args.dry_run:
        print("\n--dry-run のため sigmaris_static_verifications には記録していません。")
        return

    ids = await record_static_verification_run(run_at=run_at, baseline=baseline, results=result["results"])
    if ids or not result["results"]:
        print(f"\n✓ sigmaris_static_verifications に{len(ids)}件記録しました")
    else:
        print(
            "\n⚠ sigmaris_static_verifications への記録に失敗しました "
            "(マイグレーション202607280055未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記の検証結果自体は正しく計算されています。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--limit", type=int, default=10, help="評価対象とする、直近のD-3優先順位付け結果(normalトラック)の件数上限(デフォルト10)"
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
