#!/usr/bin/env python3
"""
Phase C-mini: 最小評価基盤 — 3指標(memory_f1_score / rag_ndcg_score /
response_error_rate)をコマンド一つで計測し、sigmaris_eval_runsに記録する。

これは内部テストセットに基づく社内指標であり、LongMemEval/LoCoMoのような
客観的な外部ベンチマークではない。B群の各機能実装後にこれを実行し、
前回との差分でその機能の効果を素早く把握する運用を想定している。

使い方:
    cd backend
    python scripts/run_eval.py
    python scripts/run_eval.py --notes "B1: xxx実装後"
    python scripts/run_eval.py --dry-run          # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SIGMARIS_REFRESH_TOKEN または SIGMARIS_USER_JWT
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_eval_runsへの記録に必要。未設定でも
    スコアの計測・標準出力は行われる — 記録だけがスキップされる)

事前準備:
    backend/eval/testset.json が必要。まだなければ先に
    `python scripts/generate_eval_testset.py` を実行すること。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Windows端末でのcp932による日本語文字化け対策。
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.eval_runner import run_eval  # noqa: E402
from app.services.eval_runs_store import get_recent_eval_runs, record_eval_run  # noqa: E402
from app.services.proactive.jwt_manager import get_sigmaris_jwt  # noqa: E402
from app.services.supabase_rest import (  # noqa: E402
    get_current_user,
    shutdown_supabase_http_client,
)

_DEFAULT_TESTSET = Path(__file__).resolve().parents[1] / "eval" / "testset.json"


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) else "N/A"


def _fmt_delta(current: float | None, previous: float | None) -> str:
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)):
        return ""
    delta = current - previous
    sign = "+" if delta >= 0 else ""
    return f" ({sign}{delta:.3f} vs前回)"


async def _main(args: argparse.Namespace) -> None:
    testset_path = Path(args.testset)
    if not testset_path.exists():
        print(
            f"ERROR: テストセットが見つかりません: {testset_path}\n"
            "先に `python scripts/generate_eval_testset.py` を実行してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    testset = json.loads(testset_path.read_text(encoding="utf-8"))

    jwt = await get_sigmaris_jwt()
    user = await get_current_user(jwt)
    user_id = user.get("id")
    if not isinstance(user_id, str):
        print("ERROR: 認証ユーザーのidが取得できません。", file=sys.stderr)
        sys.exit(1)

    print(f"評価実行中... testset={testset_path} ({len(testset.get('entries', []))}件)")
    result = await run_eval(
        jwt=jwt,
        user_id=user_id,
        testset=testset,
        search_limit=args.search_limit,
        error_window_days=args.error_window_days,
    )

    previous_runs = [] if args.dry_run else await get_recent_eval_runs(limit=1)
    previous = previous_runs[0] if previous_runs else None

    print("\n" + "=" * 60)
    print("Phase C-mini 内部評価指標 (客観ベンチマークではない社内指標)")
    print("=" * 60)
    print(f"testset_size       : {result['testset_size']} (評価対象 {result['evaluated_count']}件, "
          f"skip {len(result['skipped_entry_ids'])}件)")
    print(f"memory_precision    : {_fmt(result['memory_precision'])}"
          f"{_fmt_delta(result['memory_precision'], previous.get('memory_precision') if previous else None)}")
    print(f"memory_recall       : {_fmt(result['memory_recall'])}"
          f"{_fmt_delta(result['memory_recall'], previous.get('memory_recall') if previous else None)}")
    print(f"memory_f1_score     : {_fmt(result['memory_f1_score'])}"
          f"{_fmt_delta(result['memory_f1_score'], previous.get('memory_f1_score') if previous else None)}")
    print(f"rag_ndcg_score      : {_fmt(result['rag_ndcg_score'])}"
          f"{_fmt_delta(result['rag_ndcg_score'], previous.get('rag_ndcg_score') if previous else None)}")
    print(f"response_error_rate : {_fmt(result['response_error_rate'])}"
          f"{_fmt_delta(result['response_error_rate'], previous.get('response_error_rate') if previous else None)}"
          f"  (直近{args.error_window_days}日, n={result['response_sample_size']})")
    print(f"memory_duplicate_rate: {_fmt(result['memory_duplicate_rate'])}"
          f"{_fmt_delta(result['memory_duplicate_rate'], previous.get('memory_duplicate_rate') if previous else None)}"
          f"  (重複{result['duplicate_fact_count']}件/{result['duplicate_cluster_count']}クラスタ, "
          f"embedding有{result['duplicate_facts_with_embedding']}/{result['duplicate_total_facts']}件)")
    print("=" * 60)

    if result["skipped_entry_ids"]:
        print(f"\n注意: 正解factが現在見つからず採点できなかった設問 {len(result['skipped_entry_ids'])} 件: "
              f"{result['skipped_entry_ids']}")

    if result["duplicate_clusters"]:
        print(f"\n重複候補クラスタ ({len(result['duplicate_clusters'])}件、類似度降順):")
        for cluster in result["duplicate_clusters"][:10]:
            print(f"  類似度{cluster['max_similarity']:.3f}: {cluster['fact_ids']}")
        if len(result["duplicate_clusters"]) > 10:
            print(f"  ...他 {len(result['duplicate_clusters']) - 10} クラスタ(詳細はsigmaris_eval_runs.detailsを参照)")

    if args.dry_run:
        print("\n--dry-run のため sigmaris_eval_runs には記録していません。")
        return

    run_id = await record_eval_run(
        testset_version=result["testset_version"],
        testset_size=result["testset_size"],
        memory_precision=result["memory_precision"],
        memory_recall=result["memory_recall"],
        memory_f1_score=result["memory_f1_score"],
        rag_ndcg_score=result["rag_ndcg_score"],
        response_error_rate=result["response_error_rate"],
        response_sample_size=result["response_sample_size"],
        memory_duplicate_rate=result["memory_duplicate_rate"],
        duplicate_fact_count=result["duplicate_fact_count"],
        duplicate_cluster_count=result["duplicate_cluster_count"],
        notes=args.notes,
        details={
            "per_query": result["per_query"],
            "skipped_entry_ids": result["skipped_entry_ids"],
            "duplicate_clusters": result["duplicate_clusters"],
            "duplicate_total_facts": result["duplicate_total_facts"],
            "duplicate_facts_with_embedding": result["duplicate_facts_with_embedding"],
        },
    )
    if run_id:
        print(f"\n✓ sigmaris_eval_runs に記録しました (id={run_id})")
    else:
        print(
            "\n⚠ sigmaris_eval_runs への記録に失敗しました "
            "(マイグレーション202607060028未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記のスコア自体は正しく計測されています。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testset", default=str(_DEFAULT_TESTSET), help="テストセットJSONのパス")
    parser.add_argument("--search-limit", type=int, default=5, help="1問あたりの検索件数(search_relevant_memoriesのlimit)")
    parser.add_argument("--error-window-days", type=int, default=7, help="response_error_rateの集計期間(日数)")
    parser.add_argument("--notes", default=None, help="この実行に付けるメモ(例: 'B1実装後')")
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
