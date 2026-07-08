#!/usr/bin/env python3
"""
Phase C-full-1: LongMemEval公開ベンチマークをシグマリスの記憶パイプラインに
対して実行する。

これはLLMが自動生成した内部テストセット(Phase C-mini、run_eval.py)とは
異なり、公開されている第三者データセット(LongMemEval、MITライセンス)を
一切改変せずそのまま使う、対外的に主張できる客観的な指標である。

使い方:
    cd backend
    python scripts/run_longmemeval.py --input eval/bench_data/longmemeval_oracle.json --limit 10
    python scripts/run_longmemeval.py --input eval/bench_data/longmemeval_oracle.json --notes "初回実行"
    python scripts/run_longmemeval.py --input ... --dry-run   # DBに記録せず標準出力のみ

データセットの入手方法:
    wget https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json -P eval/bench_data/
    (s/mバリアント、あるいはoracle以外を使う場合は同じURLパターンで
    longmemeval_s_cleaned.json / longmemeval_m_cleaned.json を取得可能。
    詳細はdocs/sigmaris/phase_c_full_report.md 1章・5章を参照)

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_bench_runsへの記録・記憶の洗い流しに必要)
    SIGMARIS_EVAL_BENCH_REFRESH_TOKEN または SIGMARIS_EVAL_BENCH_USER_JWT
        (海星さん本人のSIGMARIS_REFRESH_TOKENとは別の、ベンチマーク専用
        アカウント。app/services/bench_auth.pyのモジュールdocstring参照)
    OPENAI_API_KEY (LOCAL_LLM_ENABLED=falseの場合、またはOllama疎通不可の場合)

【重要】既定では --limit を指定しない限り、ファイル内の全インスタンスを
処理する。LongMemEvalは500インスタンスあり、フルスケール実行はLLM呼び出し
コストが相応にかかる(1インスタンスあたり ingest + answer + judge の
複数回のLLM呼び出し)。小規模な動作確認には必ず --limit を指定すること。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.bench_auth import get_eval_bench_jwt, resolve_bench_user  # noqa: E402
from app.services.bench_datasets import load_longmemeval_file  # noqa: E402
from app.services.bench_pipeline import run_benchmark  # noqa: E402
from app.services.bench_runs_store import get_recent_bench_runs, record_bench_run  # noqa: E402
from app.services.bench_scoring import aggregate_bench_results  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402

_DATASET = "longmemeval"


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) else "N/A"


async def _main(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    if not input_path.exists():
        print(
            f"ERROR: LongMemEvalのデータファイルが見つかりません: {input_path}\n"
            "この docstring 冒頭の「データセットの入手方法」を参照してダウンロードしてください。",
            file=sys.stderr,
        )
        sys.exit(1)

    instances = load_longmemeval_file(input_path)
    print(f"LongMemEvalファイルを読み込みました: {input_path} ({len(instances)} インスタンス)")

    if args.limit is not None:
        instances = instances[: args.limit]
        print(f"--limit {args.limit} により、先頭 {len(instances)} 件のみ実行します。")

    jwt = await get_eval_bench_jwt()
    user_id = await resolve_bench_user(jwt)
    print(f"ベンチマーク専用アカウントで実行します (user_id={user_id})")

    def _on_instance_done(instance, results) -> None:
        correct = sum(1 for r in results if r.correct)
        print(f"  [{instance.instance_id}] {correct}/{len(results)} 正解")

    print(f"\n実行中... ({len(instances)} インスタンス、各1問)")
    results = await run_benchmark(
        instances, jwt=jwt, user_id=user_id, search_limit=args.search_limit,
        on_instance_done=_on_instance_done,
    )

    summary = aggregate_bench_results(results, dataset=_DATASET)

    previous_runs = [] if args.dry_run else await get_recent_bench_runs(_DATASET, limit=1)
    previous = previous_runs[0] if previous_runs else None

    print("\n" + "=" * 60)
    print("Phase C-full: LongMemEval (公開ベンチマーク・客観指標)")
    print("=" * 60)
    print(f"instances           : {len(instances)}")
    print(f"total_questions     : {summary.total_questions}")
    print(f"correct_count       : {summary.correct_count}")
    delta = ""
    if previous and isinstance(previous.get("overall_accuracy"), (int, float)):
        d = summary.overall_accuracy - previous["overall_accuracy"]
        delta = f" ({'+' if d >= 0 else ''}{d:.3f} vs前回)"
    print(f"overall_accuracy    : {_fmt(summary.overall_accuracy)}{delta}")
    if summary.adversarial_accuracy is not None:
        print(f"abstention_accuracy : {_fmt(summary.adversarial_accuracy)}")
    print("-" * 60)
    print("カテゴリ別正答率:")
    for category, count in sorted(summary.category_counts.items()):
        acc = summary.category_accuracy[category]
        print(f"  {category:<28} {acc:.3f}  ({summary.category_correct.get(category, 0)}/{count})")
    print("=" * 60)

    if args.dry_run:
        print("\n--dry-run のため sigmaris_bench_runs には記録していません。")
        return

    run_id = await record_bench_run(
        dataset=_DATASET,
        dataset_version=input_path.name,
        instance_count=len(instances),
        total_questions=summary.total_questions,
        correct_count=summary.correct_count,
        overall_accuracy=summary.overall_accuracy,
        category_counts=summary.category_counts,
        category_accuracy=summary.category_accuracy,
        adversarial_accuracy=summary.adversarial_accuracy,
        notes=args.notes,
        details={"per_question": summary.per_question},
    )
    if run_id:
        print(f"\n✓ sigmaris_bench_runs に記録しました (id={run_id})")
    else:
        print(
            "\n⚠ sigmaris_bench_runs への記録に失敗しました "
            "(マイグレーション202607200042未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記のスコア自体は正しく計測されています。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="LongMemEvalデータファイルのパス(JSON)")
    parser.add_argument("--limit", type=int, default=None, help="先頭N件のみ実行する(小規模動作確認用)")
    parser.add_argument("--search-limit", type=int, default=5, help="1問あたりの検索件数")
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
