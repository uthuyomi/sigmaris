#!/usr/bin/env python3
"""
Phase F-3「承認フロー、及び、承認後のプルリクエスト作成」— F-1が生成し、
安全性チェックを通過して"承認待ち"(review_status="pending")として保存
された、コード差分提案を、海星さんが確認・承認・却下するための、専用
CLI。Phase D〜Fの、自己改善の輪を閉じる、最後のステップ。

【絶対原則、繰り返し明記する】
`approve <id>` サブコマンドを、海星さんが、明示的に実行しない限り、
いかなる差分も、GitHub上のブランチ・コミット・プルリクエストへ進まない。
本スクリプトには、`list`・`show`・`approve`・`reject` の4つの
サブコマンドしか存在せず、いずれも、人間がターミナルから明示的に実行
する以外に、呼び出される経路が無い(スケジューラ・定期実行からは、
一切呼び出されない——他のいかなるRunner・cronにも、本スクリプト・
diff_approval.py::approve_diff_proposal()への参照は存在しない)。

使い方:
    cd backend
    python scripts/review_diff_proposals.py list
    python scripts/review_diff_proposals.py show <id>
    python scripts/review_diff_proposals.py approve <id> --reviewed-by "海星" --notes "確認済み、問題なし"
    python scripts/review_diff_proposals.py reject <id> --reviewed-by "海星" --notes "対象範囲が広すぎる"

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_code_diff_proposalsの読み書きに必要)
    SIGMARIS_PR_GITHUB_TOKEN, SIGMARIS_PR_GITHUB_REPO
    (approve実行時、実際にGitHub PRを作成するために必要——未設定の場合、
    approveは「承認の記録」までは行うが、PR作成はskipped_not_configured
    として記録され、実際のGitHub書き込みは発生しない)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.code_diff_proposal_store import (  # noqa: E402
    get_diff_proposal_by_id,
    get_pending_diff_proposals,
)
from app.services.constitution_guard import requires_approval  # noqa: E402
from app.services.diff_approval import approve_diff_proposal, reject_diff_proposal  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402

_TIER_LABELS = {
    "hypothesis_verified_coverage": "Tier1: E-1が既存テストのカバレッジを確認済み",
    "sandbox_infra_available_unverified_content": "Tier2: E-2でサンドボックス基盤の可用性のみ確認済み(内容は未検証)",
}


async def _cmd_list(args: argparse.Namespace) -> None:
    proposals = await get_pending_diff_proposals(limit=args.limit)
    print("=" * 60)
    print(f"承認待ちの差分提案: {len(proposals)}件(review_status=pending)")
    print("=" * 60)
    if not proposals:
        print("(承認待ちの提案はありません)")
    for p in proposals:
        tier_label = _TIER_LABELS.get(p.get("verification_tier"), p.get("verification_tier"))
        print(f"[{p.get('id')}] {p.get('title')}")
        print(f"    対象ファイル: {p.get('target_file')}")
        print(f"    検証段階: {tier_label}")
        print(f"    作成日時: {p.get('created_at')}")
    print("=" * 60)
    print("詳細は `show <id>`、承認は `approve <id>`、却下は `reject <id>` で行ってください。")


async def _cmd_show(args: argparse.Namespace) -> None:
    p = await get_diff_proposal_by_id(args.id)
    if p is None:
        print(f"提案 {args.id} が見つかりません。")
        return

    tier_label = _TIER_LABELS.get(p.get("verification_tier"), p.get("verification_tier"))
    print("=" * 60)
    print(f"差分提案: {p.get('id')}")
    print("=" * 60)
    print(f"タイトル: {p.get('title')}")
    print(f"対象ファイル: {p.get('target_file')}")
    print(f"レビュー状態: {p.get('review_status')}")
    print(f"検証段階: {tier_label}")
    print(f"検証段階の理由: {p.get('verification_tier_reason')}")
    print(f"F-1安全性チェック: {p.get('safety_check_status')}({p.get('safety_check_reason') or 'なし'})")
    print()
    # Constitution(S-4)への注意喚起。code_changeは常に承認必須カテゴリ
    # であることを、レビュー画面で毎回明示する(依頼書「Constitution
    # (S-4)に照らして注意すべき点」への対応)。
    print("--- Constitution(S-4)注記 ---")
    print(
        f"requires_approval('code_change') = {requires_approval('code_change')}"
        "  (コード変更は常に、海星さんの明示的な承認が必要なカテゴリです)"
    )
    if p.get("safety_check_status") != "passed":
        print("⚠ F-1の安全性チェックを通過していない提案です。承認操作は拒否されます。")
    print()
    print("--- 差分本文 ---")
    print(p.get("diff_text") or "(差分なし)")
    print("=" * 60)


async def _cmd_approve(args: argparse.Namespace) -> None:
    print(f"提案 {args.id} を承認します(reviewed_by={args.reviewed_by!r})...")
    outcome = await approve_diff_proposal(args.id, notes=args.notes, reviewed_by=args.reviewed_by)
    print(f"結果: status={outcome.status}, ok={outcome.ok}")
    if outcome.detail:
        print(f"詳細: {outcome.detail}")
    if outcome.pr_url:
        print(f"✓ プルリクエストを作成しました: {outcome.pr_url}")
        print("  (mainへのマージは、依然として海星さん自身が、通常のGitHub操作で行ってください)")


async def _cmd_reject(args: argparse.Namespace) -> None:
    print(f"提案 {args.id} を却下します(reviewed_by={args.reviewed_by!r})...")
    outcome = await reject_diff_proposal(args.id, notes=args.notes, reviewed_by=args.reviewed_by)
    print(f"結果: status={outcome.status}, ok={outcome.ok}")
    if outcome.detail:
        print(f"理由: {outcome.detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="承認待ちの差分提案を一覧表示する")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="1件の差分提案の詳細(差分本文込み)を表示する")
    p_show.add_argument("id")
    p_show.set_defaults(func=_cmd_show)

    p_approve = sub.add_parser("approve", help="1件の差分提案を承認し、GitHub PR作成まで実行する")
    p_approve.add_argument("id")
    p_approve.add_argument("--notes", default="")
    p_approve.add_argument("--reviewed-by", dest="reviewed_by", default="operator")
    p_approve.set_defaults(func=_cmd_approve)

    p_reject = sub.add_parser("reject", help="1件の差分提案を却下する(GitHubへは一切アクセスしない)")
    p_reject.add_argument("id")
    p_reject.add_argument("--notes", default="")
    p_reject.add_argument("--reviewed-by", dest="reviewed_by", default="operator")
    p_reject.set_defaults(func=_cmd_reject)

    args = parser.parse_args()

    async def run() -> None:
        try:
            await args.func(args)
        finally:
            await shutdown_supabase_http_client()

    asyncio.run(run())


if __name__ == "__main__":
    main()
