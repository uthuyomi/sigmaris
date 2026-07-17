# 役割: Phase F-1「仮説からコード差分への変換」のオーケストレーション
# (DB I/O・ファイル読み取りI/O)。code_diff_generation.py(生成・安全性
# チェックのロジック)にデータを渡し、E-1・D-3の記録から対象仮説を選定、
# 対象ファイルを解決・読み取り、差分を生成し、安全性チェックの結果とともに
# まとめる。
#
# 【絶対原則、このファイルにも実装しないこと】
# ファイルの読み取りは行うが(read_text()、読み取り専用)、**書き込み・
# git操作は一切行わない。** `subprocess`・`git`コマンド・GitHub API
# 呼び出しは、このファイルのどこにも存在しない。
#
# 【Phase F-2追記(docs/sigmaris/phase_f_report.md): E-1・E-2の統合】
# F-1時点では、E-1のverdict="baseline_healthy_with_coverage"のみを対象
# にしていた(hypothesis_verification.pyのTier 1相当)。F-2で、E-2の
# サンドボックス基盤が直近で健全に起動・停止できることが確認できている
# 場合に限り、E-1でverdict="insufficient_signal"だった仮説(Tier 2)も、
# 対象に加えるよう拡張した。**Tier 2は、あくまで「サンドボックス基盤が
# 使える状態にある」ことの確認であり、E-2が仮説の内容を検証したという
# 意味では全く無い**——この区別の正確な記録は、hypothesis_
# verification.pyのモジュールdocstring、およびレポートを参照。
#
# 【重要な設計判断: target_filesの欠落を、E-1のmatched_modulesで補う】
# D-3のbuild_phase_e_handoff()(hypothesis_prioritization.py)が組み立てる
# target_filesは、依頼書が指摘した通り、常にNoneの未設定プレースホルダ
# である(D-2の生成プロンプトが対象ファイル名を出力させていないため)。
# 依頼書は「target_filesが明確な仮説だけを対象とする」ことを検討するよう
# 求めているが、target_filesを字義通りに要求すると、現時点では対象仮説が
# 恒久的に0件になってしまう。
#
# 代わりに、E-1(static_verification.py)が既に算出済みの
# matched_modules(仮説の文面から推定され、かつ既存テストのカバレッジと
# 実際に一致することが確認済みのモジュール名)を、target_filesの実質的な
#代替として採用した。これは単なる代替ではなく、依頼書が求める「target_
# filesが明確」という条件を、より安全な形で満たす——matched_modulesは
# 「推定されただけ」ではなく「既存テストのカバレッジと一致することまで
# 確認済み」の情報であり、D-2のtarget_files(仮に実装されても推定に
# とどまる)より高い確度を持つ。この判断根拠は、レポートに詳述する。

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.services.code_diff_generation import (
    check_diff_safety,
    generate_diff,
)
from app.services.hypothesis_prioritization_store import get_recent_prioritization_run
from app.services.hypothesis_verification import classify_verification_tier
from app.services.migration_review_queue_store import get_queued_hypothesis_ids
from app.services.sandbox_verification_store import get_recent_sandbox_verifications
from app.services.static_verification import extract_candidate_modules
from app.services.static_verification_store import get_recent_static_verifications

logger = logging.getLogger(__name__)

_BACKEND_APP_ROOT = Path(__file__).resolve().parents[1]  # backend/app/
_REPO_ROOT = _BACKEND_APP_ROOT.parents[1]  # backend/app/ -> backend/ -> repo root

_DEFAULT_LIMIT = 10


def resolve_module_path(module_name: str) -> Path | None:
    """モジュールのベース名(例: "response_guard")から、backend/app/配下
    (backend/tests/配下は対象外——生成対象は常にアプリケーションの実装
    コードであり、テストコード自体を書き換える提案は行わない)の、実際の
    .pyファイルパスを探す。読み取り専用の検索であり、ファイルへの変更は
    一切行わない。一致するファイルが複数、または0件の場合はNone
    (曖昧な場合は無理に選ばない、という判断)。
    """
    matches = [p for p in _BACKEND_APP_ROOT.rglob(f"{module_name}.py")]
    if len(matches) != 1:
        return None
    return matches[0]


def _latest_run_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """E-1・D-3いずれも追記専用ログであり、複数run分が混在しうる。
    static_verification_store.get_recent_static_verifications()は
    run_at降順で返すため、先頭行のrun_atと一致する行だけを、直近の
    1回分の実行として扱う——hypothesis_prioritization_runner.py::
    _latest_run_normal_track()が既に確立した、同じ判断の踏襲。"""
    if not rows:
        return []
    latest_run_at = rows[0].get("run_at")
    return [r for r in rows if r.get("run_at") == latest_run_at]


async def select_candidate_hypotheses(*, limit: int = _DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """E-1・E-2の統合結果(hypothesis_verification.classify_verification_
    tier())が"not_eligible"以外と判定した仮説を対象に、D-3のphase_e_
    handoffと突き合わせ、対象ファイルを解決できたものだけを返す。

    Tier 1(hypothesis_verified_coverage、旧F-1の対象)は、E-1の
    matched_modulesをそのまま使う。Tier 2(sandbox_infra_available_
    unverified_content、F-2で追加)は、E-1のmatched_modulesが常に空
    (insufficient_signalの定義上、既存テストとの一致が無いため)である
    ため、static_verification.extract_candidate_modules()(E-1がカバレッジ
    照合の一次候補として使うのと同じ、生のテキスト抽出関数)を、仮説の
    phase_e_handoffへ直接再適用し、実在するファイルに解決できる候補を
    探す——判断根拠: Tier 2の性質上、既存テストとの一致は保証されない
    ため、E-1のカバレッジ照合済みリストではなく、その一歩手前の生の
    推定結果を再利用する。

    要件3(requires_special_review・マイグレーション仮説の除外)への
    対応: D-3のnormalトラック経由でしかsigmaris_static_verificationsに
    行が存在しない時点でrequires_special_review仮説は構造的に除外
    されており、mentions_migration()に該当する仮説はverdict=
    "excluded_migration"にしかなり得ない(baseline_healthy_with_coverage
    /insufficient_signalのいずれとも同時に成立しない、E-1の
    assess_hypothesis()の判定順序による)ため、この2つの除外は既に構造的に
    保証されている。それでも、E-4のmigration_review_queueとの突き合わせに
    よる、防御的な再確認を追加した(E-1がD-3のtrackを再確認したのと同じ、
    多層防御の判断)。
    """
    static_rows, priority_rows, queued_ids, sandbox_rows = await asyncio.gather(
        get_recent_static_verifications(limit=limit * 5),
        get_recent_prioritization_run(limit=limit * 5),
        get_queued_hypothesis_ids(),
        get_recent_sandbox_verifications(limit=1),
    )

    latest_sandbox_verification = sandbox_rows[0] if sandbox_rows else None
    priority_by_id = {row["id"]: row for row in priority_rows if row.get("id")}

    eligible_rows: list[tuple[dict[str, Any], Any]] = []
    for row in _latest_run_rows(static_rows):
        if row.get("verdict") not in ("baseline_healthy_with_coverage", "insufficient_signal"):
            continue
        tier = classify_verification_tier(row, latest_sandbox_verification=latest_sandbox_verification)
        if tier.tier == "not_eligible":
            continue
        eligible_rows.append((row, tier))

    candidates: list[dict[str, Any]] = []
    for row, tier in eligible_rows:
        hyp_id = row.get("hypothesis_id")
        if not hyp_id or hyp_id in queued_ids:
            continue  # 防御的な再確認(上記docstring参照)
        priority_row = priority_by_id.get(row.get("hypothesis_priority_id"))
        if priority_row is None:
            continue
        handoff = priority_row.get("phase_e_handoff")
        if not isinstance(handoff, dict) or not handoff:
            continue

        if tier.tier == "hypothesis_verified_coverage":
            matched_modules = row.get("matched_modules") or []
            if not matched_modules:
                continue
            module_name = matched_modules[0]  # 単一ファイルへ限定(要件、方針1)
        else:
            # Tier 2: setは順序を持たないため、決定的な選択のため
            # ソート済みの候補から、実在するファイルに解決できる最初の
            # ものを採用する(判断根拠)。
            raw_candidates = sorted(extract_candidate_modules(handoff))
            module_name = next((m for m in raw_candidates if resolve_module_path(m) is not None), None)
            if module_name is None:
                continue

        target_path = resolve_module_path(module_name)
        if target_path is None:
            continue

        candidates.append(
            {
                "hypothesis_id": hyp_id,
                "hypothesis_priority_id": row.get("hypothesis_priority_id"),
                "static_verification_id": row.get("id"),
                "title": handoff.get("title") or "",
                "what_is_problem": handoff.get("what_is_problem") or "",
                "why_problem": handoff.get("why_problem") or "",
                "how_to_improve": handoff.get("how_to_improve") or "",
                "target_module": module_name,
                "target_path": target_path,
                "verification_tier": tier.tier,
                "verification_tier_reason": tier.reason,
            }
        )
        if len(candidates) >= limit:
            break

    return candidates


async def run_code_diff_generation(*, limit: int = _DEFAULT_LIMIT) -> dict[str, Any]:
    """候補仮説それぞれについて、対象ファイルを読み取り(読み取り専用)、
    差分を生成し、安全性チェックを行う。**いかなる書き込み・git操作も
    行わない。**"""
    candidates = await select_candidate_hypotheses(limit=limit)

    proposals: list[dict[str, Any]] = []
    for c in candidates:
        target_path: Path = c["target_path"]
        try:
            file_content = target_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            logger.exception("code_diff_generation_runner: failed to read %s", target_path)
            continue

        # 例: backend/app/services/response_guard.py のような、リポジトリ
        # ルート相対のパス——実際に`git diff`が出力する形式・rollback_
        # runbook.mdが前提とするパス表記と一致させ、人間がこの差分を
        # 実際に適用する際に迷わないようにする(判断根拠)。
        relative_target = str(target_path.relative_to(_REPO_ROOT)).replace("\\", "/")

        generated = await generate_diff(
            hypothesis_title=c["title"],
            what_is_problem=c["what_is_problem"],
            why_problem=c["why_problem"],
            how_to_improve=c["how_to_improve"],
            target_file=relative_target,
            file_content=file_content,
        )
        if generated is None:
            proposals.append(
                {
                    **{k: v for k, v in c.items() if k != "target_path"},
                    "target_file": relative_target,
                    "diff_text": "",
                    "safety_check_status": "generation_failed",
                    "safety_check_reason": "LLMからの差分生成に失敗、またはファイルが大きすぎたためスキップ",
                    "review_status": "rejected",
                }
            )
            continue

        safety = check_diff_safety(generated.diff_text, expected_target_file=relative_target)
        review_status = "pending" if safety.status == "passed" else "rejected"

        proposals.append(
            {
                **{k: v for k, v in c.items() if k != "target_path"},
                "target_file": relative_target,
                "diff_text": generated.diff_text,
                "safety_check_status": safety.status,
                "safety_check_reason": safety.reason,
                "review_status": review_status,
            }
        )

    status_counts: dict[str, int] = {}
    for p in proposals:
        status_counts[p["safety_check_status"]] = status_counts.get(p["safety_check_status"], 0) + 1

    return {
        "candidates_considered": len(candidates),
        "status_counts": status_counts,
        "proposals": proposals,
    }
