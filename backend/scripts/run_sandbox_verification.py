#!/usr/bin/env python3
"""
Phase E-2「別ポートでの動的検証」— サンドボックス環境の第二段階
(docs/sigmaris/phase_e_report.md「選択肢B」)。E-1(静的検証)では判断
できなかった仮説("insufficient_signal")について、実際に動かして確認
できる範囲を広げる。

【最重要】本スクリプトは、現在の(一切変更していない)Sigmarisのコード
そのものを、本番から隔離された一時的な環境で起動し、既存の軽量な
ヘルスチェック(RC指標・Grounding指標)を実行するだけである。**E-1で
"insufficient_signal"だった仮説の内容(title/how_to_improveなど)を、
本スクリプトのどの関数にも一切渡さない・読み取らない。** 仮説をコードへ
適用する処理(Phase F相当)は、本タスクの範囲外であり、一切実装して
いない。

安全設計:
  - 本番ポート(8000)での起動をコードレベルで拒否する
  - 127.0.0.1(ループバックのみ)でbindし、LAN/Tailscaleから到達不能にする
  - PROACTIVE_ENABLED/X_ENABLED/HEALTH_SYNC_ENABLED/RESEARCH_ENABLEDを
    強制的に無効化し、外部トークン類も空にする(オペレーターの実際の
    .env設定に関わらず)
  - Phase C-full-1の専用Supabase認証アカウント(bench_auth.py)を再利用し、
    本番の記憶データには一切アクセスしない
  - 起動から既定のタイムアウト(デフォルト5分)で必ず終了する。
    terminate()→kill()の二段構えで、確実な停止を保証する

使い方:
    cd backend
    python scripts/run_sandbox_verification.py
    python scripts/run_sandbox_verification.py --port 8002 --timeout 180
    python scripts/run_sandbox_verification.py --dry-run   # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_static_verificationsの読み取り、
    およびsigmaris_sandbox_verificationsへの記録に必要)
    SIGMARIS_EVAL_BENCH_REFRESH_TOKEN または SIGMARIS_EVAL_BENCH_USER_JWT
    (Phase C-full-1の専用アカウント。未設定の場合、軽量ヘルスチェックは
    スキップされる——サンドボックスの起動・停止自体は引き続き検証される)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sandbox_verification_runner import run_sandbox_verification  # noqa: E402
from app.services.sandbox_verification_store import record_sandbox_verification  # noqa: E402
from app.services.supabase_rest import shutdown_supabase_http_client  # noqa: E402

_VERDICT_LABELS = {
    "failed_to_start": "起動失敗",
    "started_with_errors": "起動したがエラーあり",
    "started_but_checks_skipped": "起動したが検証はスキップ(benchアカウント未設定)",
    "started_and_healthy": "起動+軽量チェック正常",
}


async def _main(args: argparse.Namespace) -> None:
    print(f"Phase E-2 サンドボックス動的検証を実行中... port={args.port}, timeout={args.timeout}秒")
    print("(現在のコードをそのまま、隔離された一時環境で起動するのみ。仮説の内容は一切読みません)")
    result = await run_sandbox_verification(
        port=args.port, session_timeout_seconds=args.timeout
    )
    run_at = datetime.now(UTC).isoformat()

    print("\n" + "=" * 60)
    print("Phase E-2 サンドボックス動的検証(サンドボックス環境、第二段階)")
    print("=" * 60)
    print(f"ポート: {result.port} (127.0.0.1のみ、本番8000番とは別)")
    print(f"起動  : {'成功' if result.started else '失敗'} — {result.startup_detail}")
    print(f"停止  : {'確認済み' if result.terminated_cleanly else '⚠未確認(要手動確認)'}")
    print(f"判定  : {_VERDICT_LABELS.get(result.verdict, result.verdict)}")
    print()
    print("--- 軽量ヘルスチェック結果 ---")
    if not result.health_checks:
        print("(実行されなかった——起動に失敗したため)")
    for check in result.health_checks:
        print(f"  [{check.status}] {check.name}" + (f": {check.detail}" if check.detail else ""))
    print()
    print(f"E-1で'insufficient_signal'だった仮説候補(参考情報、内容は未参照): {len(result.candidate_hypothesis_ids)}件")
    print("=" * 60)

    if args.dry_run:
        print("\n--dry-run のため sigmaris_sandbox_verifications には記録していません。")
        return

    row_id = await record_sandbox_verification(
        run_at=run_at,
        port=result.port,
        started=result.started,
        startup_detail=result.startup_detail,
        verdict=result.verdict,
        health_checks=[asdict(c) for c in result.health_checks],
        candidate_hypothesis_ids=result.candidate_hypothesis_ids,
        terminated_cleanly=result.terminated_cleanly,
    )
    if row_id:
        print(f"\n✓ sigmaris_sandbox_verifications に記録しました (id={row_id})")
    else:
        print(
            "\n⚠ sigmaris_sandbox_verifications への記録に失敗しました "
            "(マイグレーション202607290056未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記の検証結果自体は正しく実行されています。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8001, help="サンドボックスが使用するポート(デフォルト8001、8000は使用不可)")
    parser.add_argument("--timeout", type=float, default=300.0, help="セッション全体のタイムアウト秒数(デフォルト300秒=5分)")
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
