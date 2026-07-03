#!/usr/bin/env python3
"""
Phase C-mini: 評価用テストセット(backend/eval/testset.json)の(再)生成。

実データ(user_fact_items / sigmaris_decision_log)からLLMで質問文を逆生成する。
reviewed: true が付いた既存エントリは上書きしない(人力レビューを壊さない)。

使い方:
    cd backend
    python scripts/generate_eval_testset.py
    python scripts/generate_eval_testset.py --output eval/testset.json --max-facts 20 --max-decisions 10

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SIGMARIS_REFRESH_TOKEN または SIGMARIS_USER_JWT (get_sigmaris_jwtが必要とする)
    OPENAI_API_KEY(LOCAL_LLM_ENABLED=falseの場合、または Ollama 疎通不可の場合)

【重要】ここで生成される質問文・正解ラベルはLLMによる自動生成であり、
精度に限界がある。生成後は backend/eval/testset.json を直接開いて内容を
確認し、問題があれば手で修正のうえ "reviewed": true を付けることを推奨する
(このスクリプトの再実行時、reviewed: true のエントリはそのまま保持される)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Windows端末でのcp932による日本語文字化け対策(sigmaris_chat.pyと同じ対応)。
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.proactive.jwt_manager import get_sigmaris_jwt  # noqa: E402
from app.services.supabase_rest import (  # noqa: E402
    get_current_user,
    shutdown_supabase_http_client,
)
from app.services.testset_gen import build_testset  # noqa: E402

_DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "eval" / "testset.json"


async def _main(args: argparse.Namespace) -> None:
    output_path = Path(args.output)

    existing: dict | None = None
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        reviewed_count = sum(1 for e in existing.get("entries", []) if e.get("reviewed"))
        print(f"既存テストセットを読み込みました: {output_path} (reviewed済み {reviewed_count} 件を保持)")

    jwt = await get_sigmaris_jwt()
    user = await get_current_user(jwt)
    user_id = user.get("id")
    if not isinstance(user_id, str):
        print("ERROR: 認証ユーザーのidが取得できません。", file=sys.stderr)
        sys.exit(1)

    print(f"テストセットを生成中... (max_facts={args.max_facts}, max_decisions={args.max_decisions})")
    testset = await build_testset(
        jwt=jwt,
        user_id=user_id,
        max_fact_questions=args.max_facts,
        max_decision_questions=args.max_decisions,
        seed=args.seed,
        existing=existing,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(testset, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✓ {len(testset['entries'])} 件のテストセットを書き出しました: {output_path}")
    fact_count = sum(1 for e in testset["entries"] if e["source"] == "fact")
    decision_count = sum(1 for e in testset["entries"] if e["source"] == "decision")
    print(f"  内訳: fact由来 {fact_count} 件 / decision由来 {decision_count} 件")
    print("  ※ LLMによる自動生成のため、内容を確認のうえ問題があれば修正し reviewed:true を付けてください。")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(_DEFAULT_OUTPUT), help="出力先JSONパス")
    parser.add_argument("--max-facts", type=int, default=20, help="fact由来の設問の最大数")
    parser.add_argument("--max-decisions", type=int, default=10, help="decision由来の設問の最大数")
    parser.add_argument("--seed", type=int, default=42, help="サンプリングの乱数シード(再現性のため)")
    args = parser.parse_args()

    async def run() -> None:
        try:
            await _main(args)
        finally:
            await shutdown_supabase_http_client()

    asyncio.run(run())


if __name__ == "__main__":
    main()
