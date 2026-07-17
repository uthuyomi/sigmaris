#!/usr/bin/env python3
"""
Phase D-2「仮説生成」— 改良提案エンジン(Phase D)の第二段階。D-1が最後に
記録した根拠一覧(sigmaris_evidence_bundles)から、優先度の高い根拠を対象に、
LLMで具体的な改良仮説を組み立てる。

  1. 生成    根拠1件につき仮説1件をLLMで生成(TaskType.HYPOTHESIS_
             GENERATION、advanced tier)
  2. フィルタ ルールベースで、抽象的すぎる仮説・根拠と字句的に無関係な
             仮説を除外
  3. 検証    独立した批評家(TaskType.HYPOTHESIS_CRITIQUE、nano tier、
             G-3のSelf-Critique方式の応用)が、仮説の主張が根拠から
             論理的に導けるかを判定。導けない場合は除外
  4. Constitution連携 既存の安全機構(response_guard.py・B11・
             constitution_guard.py等)に触れる仮説を検出し、
             requires_special_review=trueでフラグ立て。フラグが立った
             仮説は、通常の仮説より後ろに並べ替える(優先順位を下げる)

【重要】本スクリプトは仮説の生成のみを行う。実際のコード変更・実行・
承認フローの実行は一切行わない(次タスクD-3、Phase F相当はスコープ外)。

使い方:
    cd backend
    python scripts/run_hypothesis_generation.py
    python scripts/run_hypothesis_generation.py --top-n 10
    python scripts/run_hypothesis_generation.py --dry-run   # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_evidence_bundlesの読み取り、
    およびsigmaris_hypothesesへの記録に必要)
    OPENAI_API_KEY (HYPOTHESIS_GENERATION/HYPOTHESIS_CRITIQUEの実行に必要)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.hypothesis_generation_runner import run_hypothesis_generation  # noqa: E402
from app.services.hypothesis_store import record_hypotheses  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402


async def _main(args: argparse.Namespace) -> None:
    print(f"Phase D-2 仮説生成を実行中... top_n={args.top_n}")
    result = await run_hypothesis_generation(top_n_items=args.top_n)

    print("\n" + "=" * 60)
    print("Phase D-2 仮説生成(改良提案エンジンの、材料組み立て層)")
    print("=" * 60)
    print(f"入力元 evidence_bundle_id : {result['evidence_bundle_id']}")
    print(f"入力元 evidence_bundle実行時刻: {result['evidence_bundle_run_at']}")
    if result["evidence_bundle_id"] is None:
        print("(sigmaris_evidence_bundlesが0件——D-1が未実行、または")
        print(" マイグレーション202607250052が未適用の可能性)")
    print()
    print(f"検討した根拠件数         : {result['candidates_considered']}")
    print(f"生成成功件数             : {result['generated_count']}")
    print(f"除外(抽象的/根拠なし)件数 : {result['filtered_vague_count']}")
    print(f"除外(対応関係の検証失敗)件数: {result['filtered_ungrounded_count']}")
    print(f"要レビューフラグ件数      : {result['flagged_for_review_count']}")
    print(f"最終的に採用された仮説件数: {result['kept_count']}")
    print()
    print("--- 仮説一覧(要レビュー分は末尾に配置) ---")
    if not result["hypotheses"]:
        print("(仮説は0件——根拠が無い、または全て除外された可能性がある。")
        print(" 0件は「改善不要」を意味するとは限らない点に注意)")
    for h in result["hypotheses"]:
        review_mark = "[要レビュー] " if h["requires_special_review"] else ""
        print(f"- {review_mark}{h['title']}")
        print(f"    根拠: {h['source_evidence_category']}/{h['source_evidence_title']}")
        print(f"    何が問題か: {h['what_is_problem']}")
        print(f"    どう改善するか: {h['how_to_improve']}")
        if h["expected_metric_improvements"]:
            print(f"    期待される指標改善: {', '.join(h['expected_metric_improvements'])}")
        if h["requires_special_review"]:
            print(f"    レビュー理由: {h['safety_review_reason']}")
    print("=" * 60)

    if args.dry_run:
        print("\n--dry-run のため sigmaris_hypotheses には記録していません。")
        return

    ids = await record_hypotheses(result["evidence_bundle_id"], result["hypotheses"])
    if ids or not result["hypotheses"]:
        print(f"\n✓ sigmaris_hypotheses に{len(ids)}件記録しました")
    else:
        print(
            "\n⚠ sigmaris_hypotheses への記録に失敗しました "
            "(マイグレーション202607260053未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記の仮説自体は正しく生成されています。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--top-n", type=int, default=5, help="直近のevidence bundleから対象とする根拠の件数上限(デフォルト5)"
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
