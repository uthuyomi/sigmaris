#!/usr/bin/env python3
"""
Phase R-2: 循環健全性指標(RC指標) — RC-1(Cycle Completion Rate)・
RC-2(Temporal Consistency Score)をコマンド一つで計測する。

【重要】これはC-mini/C-full(run_eval.py、memory_precision等)とは
別系統の指標である。C-mini/C-fullが「記憶検索の精度」を測るのに対し、
RC指標はExperience→Memory→...→Policyという循環そのものが機能している
かを測る。両者を同じ数値として比較・混同しないこと(docs/sigmaris/
phase_r_report.md参照)。

指標の解釈にあたっての注意:
  - RC-1(raw_completion_rate)が低い/高いこと自体は、単独では「良い/
    悪い」を意味しない。多くのExperienceがMemoryに昇格しないのは
    Phase B2の設計上正常な挙動である(裏付けとなる複数のエピソードが
    ないと昇格しない)。reason_countsの内訳(特にevaluated_not_promoted
    の件数)を見ること。
  - RC-2(score)がNoneの場合は「矛盾ゼロ」ではなく「検査対象が0件
    だった」ことを意味する。checked件数と併せて解釈すること。

使い方:
    cd backend
    python scripts/run_cycle_health.py
    python scripts/run_cycle_health.py --window-days 60

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SIGMARIS_REFRESH_TOKEN または SIGMARIS_USER_JWT
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_experience/sigmaris_decision_log等
    のservice-role専用テーブルの読み取りに必要)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Windows端末でのcp932による日本語文字化け対策(run_eval.pyと同じ対応)。
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.cycle_health_runner import run_cycle_health  # noqa: E402
from app.services.proactive.jwt_manager import get_sigmaris_jwt  # noqa: E402
from app.services.supabase_rest import (  # noqa: E402
    get_current_user,
    shutdown_supabase_http_client,
)


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) else "N/A"


async def _main(args: argparse.Namespace) -> None:
    jwt = await get_sigmaris_jwt()
    user = await get_current_user(jwt)
    if not isinstance(user.get("id"), str):
        print("ERROR: 認証ユーザーのidが取得できません。", file=sys.stderr)
        sys.exit(1)

    print(f"循環健全性を計測中... window={args.window_days}日")
    result = await run_cycle_health(jwt=jwt, window_days=args.window_days)

    rc1 = result["rc1_cycle_completion"]
    rc2 = result["rc2_temporal_consistency"]

    print("\n" + "=" * 60)
    print("Phase R-2 循環健全性指標 (RC指標。C-mini/C-fullとは別系統)")
    print("=" * 60)
    print(f"計測期間           : {rc2['period_from']} 〜 {rc2['period_to']}")
    print()
    print("--- RC-1: Cycle Completion Rate ---")
    print(f"対象Experience数    : {rc1['total_experiences']}")
    print(f"Memory到達数        : {rc1['reached_count']}")
    print(f"raw_completion_rate : {_fmt(rc1['raw_completion_rate'])}"
          f"  (単純到達率。低いこと自体は異常ではない — 下記reason参照)")
    print(f"eligible_completion_rate: {_fmt(rc1['eligible_completion_rate'])}"
          f"  (タイミング/母数不足で構造的に説明できる非到達を除いた率)")
    print(f"直近の想定バッチ実行時刻: {rc1['last_scheduled_consolidation_at']}")
    if rc1["reason_counts"]:
        print("非到達の内訳:")
        for reason, count in sorted(rc1["reason_counts"].items(), key=lambda kv: -kv[1]):
            print(f"  {reason:32s}: {count}件")
    print()
    print("--- RC-2: Temporal Consistency Score ---")
    print(f"score               : {_fmt(rc2['score'])}"
          f"  (Noneは「矛盾ゼロ」ではなく「検査対象0件」を意味する)")
    print(f"  chat_messages順序  : 違反{len(rc2['chat_order_violations'])}件 / "
          f"検査ペア{rc2['chat_pairs_checked']}件 (スレッド{rc2['chat_threads_checked']}件)")
    print(f"  タイムスタンプ崩壊 : {_fmt(rc2['chat_collapsed_timestamp_ratio'])}"
          f"  (参考値、スコアには直接反映されない。過去の汚染データの残存度の目安)")
    print(f"  event⇔Experience   : 違反{len(rc2['event_experience_violations'])}件 / "
          f"検査{rc2['event_experience_checked']}件")
    print("=" * 60)

    if rc2["chat_order_violations"]:
        print(f"\nchat_messages順序違反の例(最大5件):")
        for v in rc2["chat_order_violations"][:5]:
            print(f"  thread={v['thread_id']} index={v['index_in_thread']} "
                  f"prev={v['prev_created_at']} -> created_at={v['created_at']}")

    if rc2["event_experience_violations"]:
        print(f"\nevent⇔Experience矛盾の例(最大5件):")
        for v in rc2["event_experience_violations"][:5]:
            print(f"  fact={v['fact_id']}(created={v['fact_created_at']}) "
                  f"< experience={v['experience_id']}(created={v['experience_created_at']})")

    print(
        "\n注意: RC指標はまだsigmaris_eval_runs等への永続化を行っていない"
        "(本タスクのスコープ外、docs/sigmaris/phase_r_report.md参照)。"
        "この標準出力が現時点での唯一の記録手段である。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--window-days", type=int, default=30, help="計測対象期間(日数、デフォルト30日)")
    args = parser.parse_args()

    async def run() -> None:
        try:
            await _main(args)
        finally:
            await shutdown_supabase_http_client()

    asyncio.run(run())


if __name__ == "__main__":
    main()
