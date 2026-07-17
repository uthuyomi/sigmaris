#!/usr/bin/env python3
"""
循環健全性指標(RC指標) — RC-1〜RC-5をコマンド一つで計測する。

  RC-1 Cycle Completion Rate      Experience -> Memoryへの到達率
  RC-2 Temporal Consistency Score 時間的にありえない矛盾の検出
  RC-3 Belief Stability Index     信念(B14)が根拠なく覆っていないか
  RC-4 Policy-Belief Alignment    方策(B16)が信念(B14)と同じ材料に基づくか
  RC-5 Cycle Break Detection      RC-1/RC-2の急激な悪化の検知

  Safety Governance                安全上重要なファイルの追加登録漏れ検知
                                    (Safety-3、RC指標とは別系統だが同じ
                                    測定基盤に統合。docs/sigmaris/
                                    safety_governance_report.md参照)

【重要】これはC-mini/C-full(run_eval.py、memory_precision等)とは
別系統の指標である。C-mini/C-fullが「記憶検索の精度」を測るのに対し、
RC指標はExperience→Memory→...→Policyという循環そのものが機能している
かを測る。両者を同じ数値として比較・混同しないこと(docs/sigmaris/
phase_r_report.md参照)。

指標の解釈にあたっての注意:
  - RC-1(raw_completion_rate)が低い/高いこと自体は、単独では「良い/
    悪い」を意味しない。reason_countsの内訳を見ること。
  - RC-2/RC-3/RC-4のscoreがNoneの場合は「矛盾/変化ゼロ」ではなく
    「検査・比較対象が0件だった」ことを意味する。RC-3は初回実行時(前回
    スナップショットが存在しない)は必ずNoneになる。
  - RC-5はRC-1/RC-2のみを対象とする(要件通り、RC-3/RC-4は対象外)。
    status="insufficient_history"は「異常なし」ではなく「まだ履歴が
    足りず判定できない」ことを意味する(直近3回以上の記録後に意味を
    持ち始める)。

使い方:
    cd backend
    python scripts/run_cycle_health.py
    python scripts/run_cycle_health.py --window-days 60
    python scripts/run_cycle_health.py --dry-run   # DBに記録せず標準出力のみ

必要な環境変数(backend/.env):
    NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
    SIGMARIS_REFRESH_TOKEN または SIGMARIS_USER_JWT
    SUPABASE_SERVICE_ROLE_KEY (sigmaris_experience等のservice-role専用
    テーブルの読み取り、およびsigmaris_cycle_health_runsへの記録に必要)
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
from app.services.cycle_health_runs_store import record_cycle_health_run  # noqa: E402
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
    rc3 = result["rc3_belief_stability"]
    rc4 = result["rc4_policy_belief_alignment"]
    rc5 = result["rc5_cycle_break"]
    safety_gov = result["safety_governance"]

    print("\n" + "=" * 60)
    print("循環健全性指標 (RC指標。C-mini/C-fullとは別系統)")
    print("=" * 60)
    print(f"計測期間           : {result['period_from']} 〜 {result['period_to']}")
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
    print(f"  chat_messages順序  : 違反{rc2['chat_order_violation_count']}件 / "
          f"検査ペア{rc2['chat_pairs_checked']}件 (スレッド{rc2['chat_threads_checked']}件)")
    print(f"  タイムスタンプ崩壊 : {_fmt(rc2['chat_collapsed_timestamp_ratio'])}"
          f"  (参考値、スコアには直接反映されない)")
    print(f"  event⇔Experience   : 違反{rc2['event_experience_violation_count']}件 / "
          f"検査{rc2['event_experience_checked']}件")
    print()
    print("--- RC-3: Belief Stability Index ---")
    if not rc3["has_previous_snapshot"]:
        print("score               : N/A (前回実行のスナップショットが存在しないため算出不能。次回実行以降で算出される)")
    else:
        print(f"score               : {_fmt(rc3['score'])}"
              f"  (比較可能{rc3['comparable_pattern_count']}件中、根拠不十分な反転{rc3['unsupported_flip_count']}件)")
        print(f"  信念の反転         : {rc3['flip_count']}件 (うち根拠不十分{rc3['unsupported_flip_count']}件)")
    print()
    print("--- RC-4: Policy-Belief Alignment ---")
    print(f"score               : {_fmt(rc4['score'])}"
          f"  (評価対象フラグ{rc4['flags_evaluated']}件。Noneは評価対象0件を意味する)")
    print()
    print("--- RC-5: Cycle Break Detection ---")
    print(f"status              : {rc5['status']}"
          f"  (insufficient_historyは「異常なし」ではなく「履歴不足で未判定」)")
    if rc5["broke_metrics"]:
        print(f"  悪化を検知した指標 : {', '.join(rc5['broke_metrics'])}")
    print()
    print("--- Safety Governance: 安全上重要なファイルの追加登録漏れ検知(Safety-3) ---")
    print(f"status              : {safety_gov['status']}"
          f"  (RC-5とは別系統、履歴不要の瞬間的な構造チェック)")
    print(f"スキャン対象ファイル数: {safety_gov['scanned_file_count']}"
          f" / ゲートらしいパターン一致: {safety_gov['gate_pattern_file_count']}"
          f" / 未登録候補: {safety_gov['unregistered_count']}")
    if safety_gov["unregistered_files"]:
        print("  未登録候補ファイル(自動追加はしません、人間が判断してください):")
        for path in safety_gov["unregistered_files"]:
            print(f"    - {path}")
    print("=" * 60)

    if rc2["chat_order_violations"]:
        print("\nchat_messages順序違反の例(最大5件):")
        for v in rc2["chat_order_violations"][:5]:
            print(f"  thread={v['thread_id']} index={v['index_in_thread']} "
                  f"prev={v['prev_created_at']} -> created_at={v['created_at']}")

    if rc2["event_experience_violations"]:
        print("\nevent⇔Experience矛盾の例(最大5件):")
        for v in rc2["event_experience_violations"][:5]:
            print(f"  fact={v['fact_id']}(created={v['fact_created_at']}) "
                  f"< experience={v['experience_id']}(created={v['experience_created_at']})")

    if safety_gov["status"] == "gap_detected":
        # RC-5と同じ判断根拠(通知の実装自体は見送り、既存のnotifier経由の
        # 統合はいつでも可能な状態にしておく)を踏襲。
        print(
            "\n⚠ Safety Governanceが、未登録の可能性がある安全上重要なファイルを検知しました。"
            "通知は未実装のため、この標準出力とsigmaris_cycle_health_runs."
            "safety_governance_statusが現時点での唯一の検知手段です。"
            "\n  scripts/scan_safety_critical_files.py で詳細を確認してください。"
        )

    if rc5["status"] == "break_detected":
        # 判断根拠(docs/sigmaris/phase_r_report.md参照): 通知の実装自体は
        # 本タスクの必須要件ではないため見送っているが、既存の
        # app.services.proactive.notifier.get_notifier().send(title, message)
        # がPushover/LogNotifierを抽象化済みであり、ここに1行追加するだけ
        # で通知に統合できる状態になっている。
        print(
            "\n⚠ RC-5がcycle break(循環の急激な悪化)を検知しました。"
            "通知は未実装のため、この標準出力とsigmaris_cycle_health_runs.rc5_statusが"
            "現時点での唯一の検知手段です。"
        )

    if args.dry_run:
        print("\n--dry-run のため sigmaris_cycle_health_runs には記録していません。")
        return

    run_id = await record_cycle_health_run(
        window_days=result["window_days"],
        period_from=result["period_from"],
        period_to=result["period_to"],
        rc1={
            "total_experiences": rc1["total_experiences"],
            "reached_count": rc1["reached_count"],
            "raw_completion_rate": rc1["raw_completion_rate"],
            "eligible_count": rc1["eligible_count"],
            "eligible_completion_rate": rc1["eligible_completion_rate"],
        },
        rc2={
            "score": rc2["score"],
            "chat_pairs_checked": rc2["chat_pairs_checked"],
            "chat_order_violation_count": rc2["chat_order_violation_count"],
            "event_experience_checked": rc2["event_experience_checked"],
            "event_experience_violation_count": rc2["event_experience_violation_count"],
        },
        rc3={
            "score": rc3["score"],
            "comparable_pattern_count": rc3["comparable_pattern_count"],
            "flip_count": rc3["flip_count"],
            "unsupported_flip_count": rc3["unsupported_flip_count"],
        },
        rc4={"score": rc4["score"], "flags_evaluated": rc4["flags_evaluated"]},
        rc5={"status": rc5["status"], "broke_metrics": rc5["broke_metrics"]},
        safety_governance={
            "status": safety_gov["status"],
            "unregistered_count": safety_gov["unregistered_count"],
        },
        notes=args.notes,
        details=result["details_for_persistence"],
    )
    if run_id:
        print(f"\n✓ sigmaris_cycle_health_runs に記録しました (id={run_id})")
    else:
        print(
            "\n⚠ sigmaris_cycle_health_runs への記録に失敗しました "
            "(マイグレーション202607220048未適用、またはSUPABASE_SERVICE_ROLE_KEY未設定の可能性)。"
            "上記のスコア自体は正しく計測されています。"
            "\n  注意: RC-3(次回比較用スナップショット)・RC-5(履歴ベースライン)は"
            "この記録に依存するため、記録が失敗し続けると両指標が算出不能のまま推移します。"
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
