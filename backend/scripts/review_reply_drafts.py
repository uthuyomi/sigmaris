#!/usr/bin/env python3
"""
Phase H-3「承認フロー、及び、実際の投稿」— H-2.5が生成し、"投稿待ち"
(reply_draft_status="pending_post")として保存された、X返信案を、海星さん
が確認・承認・却下するための、専用CLI。Phase H(X投稿連携)、及び、当初の
ロードマップ(Phase A〜H)全体の輪を閉じる、最後のステップ。F-3
(review_diff_proposals.py)と、同じ構造・同じ絶対原則。

【絶対原則、繰り返し明記する】
`approve <id>` サブコマンドを、海星さんが、明示的に実行しない限り、
いかなる返信案も、実際にXへ投稿されない。本スクリプトには、`list`・
`show`・`approve`・`reject` の4つのサブコマンドしか存在せず、いずれも、
人間がターミナルから明示的に実行する以外に、呼び出される経路が無い
(スケジューラ・定期実行からは、一切呼び出されない——他のいかなる
Runner・cronにも、本スクリプト・reply_approval.py::approve_reply_
draft()への参照は存在しない)。`@Oyasu1999`への返信であっても、この
承認フローは省略されない。

使い方:
    cd backend
    python scripts/review_reply_drafts.py list
    python scripts/review_reply_drafts.py show <id>
    python scripts/review_reply_drafts.py approve <id> --reviewed-by "海星" --notes "確認済み、問題なし"
    python scripts/review_reply_drafts.py reject <id> --reviewed-by "海星" --notes "この返信はしない"

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SUPABASE_SERVICE_ROLE_KEY (x_reply_logの読み書きに必要)
    X_ENABLED, X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
    (approve実行時、実際にXへ投稿するために必要——未設定の場合、
    approveは「承認の記録」までは行うが、実際の投稿はLogPublisher
    (ログ出力のみ)によってシミュレーションされ、実際のX APIへの
    書き込みは発生しない)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.constitution_guard import requires_approval  # noqa: E402
from app.services.reply_approval import approve_reply_draft, reject_reply_draft  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402
from app.services.x_reply_log_store import (  # noqa: E402
    get_reply_draft_by_id,
    get_reply_drafts_pending_review,
)

_AUDIENCE_LABELS = {
    "developer": "開発者(@Oyasu1999)向け",
    "general": "一般ユーザー向け",
}


async def _cmd_list(args: argparse.Namespace) -> None:
    rows = await get_reply_drafts_pending_review(limit=args.limit)
    print("=" * 60)
    print(f"承認待ちの返信案: {len(rows)}件(reply_draft_status=pending_post, review_status=pending)")
    print("=" * 60)
    if not rows:
        print("(承認待ちの返信案はありません)")
    for r in rows:
        audience_label = _AUDIENCE_LABELS.get(r.get("reply_draft_audience"), r.get("reply_draft_audience"))
        print(f"[{r.get('id')}] {audience_label}")
        print(f"    相手の返信: {(r.get('reply_text') or '')[:60]}")
        print(f"    返信案: {r.get('reply_draft_text')}")
        print(f"    生成日時: {r.get('reply_draft_generated_at')}")
    print("=" * 60)
    print("詳細は `show <id>`、承認は `approve <id>`、却下は `reject <id>` で行ってください。")


async def _cmd_show(args: argparse.Namespace) -> None:
    r = await get_reply_draft_by_id(args.id)
    if r is None:
        print(f"返信案 {args.id} が見つかりません。")
        return

    audience_label = _AUDIENCE_LABELS.get(r.get("reply_draft_audience"), r.get("reply_draft_audience"))
    print("=" * 60)
    print(f"返信案: {r.get('id')}")
    print("=" * 60)
    print(f"発信元: {r.get('author_username') or '(不明)'}({audience_label})")
    print(f"H-2フィルタ判定: {r.get('filter_outcome')}")
    print(f"レビュー状態: {r.get('review_status')}")
    print(f"投稿状態: {r.get('post_status') or '(未実行)'}")
    print()
    print("--- 相手からの返信(元の投稿) ---")
    print(r.get("reply_text") or "(なし)")
    print()
    print("--- 生成された返信案 ---")
    print(r.get("reply_draft_text") or "(なし)")
    print()
    # Constitution(S-4)への注意喚起。external_transmissionは常に承認必須
    # カテゴリであることを、レビュー画面で毎回明示する(F-3のshowコマンド
    # と同じ、依頼書「Constitution(S-4)に照らして注意すべき点」への対応)。
    print("--- Constitution(S-4)注記 ---")
    print(
        f"requires_approval('external_transmission') = {requires_approval('external_transmission')}"
        "  (Xへの投稿は常に、海星さんの明示的な承認が必要なカテゴリです)"
    )
    if r.get("reply_draft_audience") == "developer":
        print("⚠ 開発者(@Oyasu1999)への返信ですが、承認フローは省略されません。")
    print("=" * 60)


async def _cmd_approve(args: argparse.Namespace) -> None:
    print(f"返信案 {args.id} を承認します(reviewed_by={args.reviewed_by!r})...")
    outcome = await approve_reply_draft(args.id, notes=args.notes, reviewed_by=args.reviewed_by)
    print(f"結果: status={outcome.status}, ok={outcome.ok}")
    if outcome.detail:
        print(f"詳細: {outcome.detail}")
    if outcome.tweet_id:
        print(f"✓ Xに投稿しました: tweet_id={outcome.tweet_id}")


async def _cmd_reject(args: argparse.Namespace) -> None:
    print(f"返信案 {args.id} を却下します(reviewed_by={args.reviewed_by!r})...")
    outcome = await reject_reply_draft(args.id, notes=args.notes, reviewed_by=args.reviewed_by)
    print(f"結果: status={outcome.status}, ok={outcome.ok}")
    if outcome.detail:
        print(f"理由: {outcome.detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="承認待ちの返信案を一覧表示する")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="1件の返信案の詳細を表示する")
    p_show.add_argument("id")
    p_show.set_defaults(func=_cmd_show)

    p_approve = sub.add_parser("approve", help="1件の返信案を承認し、実際にXへ投稿する")
    p_approve.add_argument("id")
    p_approve.add_argument("--notes", default="")
    p_approve.add_argument("--reviewed-by", dest="reviewed_by", default="operator")
    p_approve.set_defaults(func=_cmd_approve)

    p_reject = sub.add_parser("reject", help="1件の返信案を却下する(Xへは一切アクセスしない)")
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
