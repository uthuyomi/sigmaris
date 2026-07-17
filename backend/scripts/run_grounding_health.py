#!/usr/bin/env python3
"""
Phase G継続測定 — Citation Precision・Search Trigger Rate・Contradiction
Rateをコマンド一つで計測する。

  Citation Precision    引用されたclaimのうち、正しく主張を裏付けていた割合
  Search Trigger Rate   全ターンのうち、検索が実行され監査ログが残った割合
                        (G-1のneeds_search=true判定そのものの下限近似値)
  Contradiction Rate    検証済みターンのうち、矛盾・不正確な使い方が
                        検出された割合

【重要】これはcycle_health(RC指標、Phase R)ともeval_runs(C-mini/
C-full、memory_precision等)とも別系統の指標である。RC指標が「循環
そのものが機能しているか」、C-mini/C-fullが「記憶検索の精度」を測るのに
対し、Phase Gの指標は「検索・引用の精度」を測る。三者を同じ数値として
比較・混同しないこと(docs/sigmaris/phase_g_report.md参照)。

指標の解釈にあたっての注意:
  - 3指標ともNoneの場合は「0%/100%」ではなく「算出対象0件」を意味する。
  - Search Trigger Rateは、G-1のneeds_search判定そのものを永続化して
    いないため、実際の発動率より低く出る可能性がある下限近似値である
    (詳細はgrounding_health_metrics.py::compute_search_trigger_rate()の
    docstring、および本報告書の懸念点を参照)。「低い=検索判定が
    機能していない」と短絡的に解釈しないこと。
  - Search Trigger Rateが低いこと自体は、必ずしも悪いことではない
    (そもそも検索が必要な質問が少なかっただけの可能性がある)。
  - Contradiction Rateの分母は「検証が実際に行われたターン」のみで
    あり、全ターンではない。

使い方:
    cd backend
    python scripts/run_grounding_health.py
    python scripts/run_grounding_health.py --window-days 60
    python scripts/run_grounding_health.py --dry-run   # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SIGMARIS_REFRESH_TOKEN または SIGMARIS_USER_JWT
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_citation_audit_logの読み取り、
    およびsigmaris_grounding_health_runsへの記録に必要)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Windows端末でのcp932による日本語文字化け対策(run_cycle_health.pyと同じ対応)。
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.grounding_health_runner import run_grounding_health  # noqa: E402
from app.services.grounding_health_runs_store import record_grounding_health_run  # noqa: E402
from app.services.proactive.jwt_manager import get_sigmaris_jwt  # noqa: E402
from app.services.supabase_rest import (  # noqa: E402
    get_current_user,
    shutdown_supabase_http_client,
)


def _fmt_rate(value: float | None) -> str:
    return f"{value:.1%}" if isinstance(value, (int, float)) else "N/A"


async def _main(args: argparse.Namespace) -> None:
    jwt = await get_sigmaris_jwt()
    user = await get_current_user(jwt)
    if not isinstance(user.get("id"), str):
        print("ERROR: 認証ユーザーのidが取得できません。", file=sys.stderr)
        sys.exit(1)

    print(f"Phase G継続測定を計測中... window={args.window_days}日")
    result = await run_grounding_health(jwt=jwt, window_days=args.window_days)

    cp = result["citation_precision"]
    str_ = result["search_trigger_rate"]
    cr = result["contradiction_rate"]

    print("\n" + "=" * 60)
    print("Phase G継続測定 (Grounding指標。RC指標/C-mini/C-fullとは別系統)")
    print("=" * 60)
    print(f"計測期間           : {result['period_from']} 〜 {result['period_to']}")
    print()
    print("--- Citation Precision(引用精度) ---")
    print(f"precision           : {_fmt_rate(cp['precision'])}"
          f"  (Noneは「引用されたclaimが0件」を意味する)")
    print(f"  faithful          : {cp['faithful_count']}件")
    print(f"  distorted         : {cp['distorted_count']}件")
    print(f"  not_used(参考)    : {cp['not_used_count']}件(分母には含めない)")
    print()
    print("--- Search Trigger Rate(検索発動率) ---")
    print(f"rate                : {_fmt_rate(str_['rate'])}"
          f"  (下限近似値 — 詳細は本スクリプトのヘッダコメント参照)")
    print(f"  監査ログが残ったターン数: {str_['audited_turns']}")
    print(f"  全ターン数             : {str_['total_turns']}")
    print()
    print("--- Contradiction Rate(矛盾検出率) ---")
    print(f"rate                : {_fmt_rate(cr['rate'])}"
          f"  (Noneは「検証が行われたターンが0件」を意味する)")
    print(f"  フラグが立ったターン数  : {cr['flagged_turns']}")
    print(f"  検証が行われたターン数  : {cr['audited_turns']}")
    print("=" * 60)

    if args.dry_run:
        print("\n--dry-run のため sigmaris_grounding_health_runs には記録していません。")
        return

    run_id = await record_grounding_health_run(
        window_days=result["window_days"],
        period_from=result["period_from"],
        period_to=result["period_to"],
        citation_precision=cp,
        search_trigger_rate=str_,
        contradiction_rate=cr,
        notes=args.notes,
        details=result["details_for_persistence"],
    )
    if run_id:
        print(f"\n✓ sigmaris_grounding_health_runs に記録しました (id={run_id})")
    else:
        print(
            "\n⚠ sigmaris_grounding_health_runs への記録に失敗しました "
            "(マイグレーション202607240051未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記のスコア自体は正しく計測されています。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--window-days", type=int, default=30, help="計測対象期間(日数、デフォルト30日)")
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
