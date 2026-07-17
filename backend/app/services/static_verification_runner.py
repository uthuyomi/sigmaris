# 役割: Phase E-1「静的検証パイプライン」のオーケストレーション(I/O)。
# static_verification.py(純粋関数)にデータを渡し、D-3の優先順位付け
# 結果(sigmaris_hypothesis_priorities)を対象に静的検証を行う。
#
# 【最重要・繰り返し明記】このモジュールが行うI/Oは、以下の2種類のみ
# であり、いずれもコードを一切変更しない。
#   1. 既存の(変更していない)backend/tests/を、そのままsubprocessで
#      実行する(ベースライン確認) —— これは依頼書が「最もリスクの低い
#      方法」として明示的に例示した方式そのもの
#   2. 既存の(変更していない)backend/tests/配下の*.pyファイルを、
#      読み取り専用でファイルシステムから読む(カバレッジ照合用)
# 仮説の内容に基づいてコードを書き換える処理は、このファイルにも
# static_verification.pyにも一切存在しない。

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.hypothesis_prioritization_store import get_recent_prioritization_run
from app.services.static_verification import BaselineResult, assess_hypothesis, parse_imported_app_modules

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_TESTS_DIR = _BACKEND_ROOT / "tests"

_DEFAULT_LIMIT = 10


async def run_baseline_test_suite(*, timeout_seconds: float = 120.0) -> BaselineResult:
    """backend/tests/を、そのまま(一切変更せず)subprocessでpytest実行
    する。読み取り専用の確認であり、テストファイル・アプリケーション
    コードのいずれも書き換えない——依頼書が例示した「既存のテストを、
    そのまま実行して、現状で全て通っていることを確認するベースライン
    確認」そのものの実装。

    scratchテストではなくbackend/tests/のみを対象にした判断根拠:
    scratchテストはセッションスコープで永続化されない
    (`docs/sigmaris/codebase_size_report.md` 5.2節)ため、次回セッション
    では既に存在しない。E-1は将来にわたって繰り返し実行されるCLIである
    以上、常に存在することが保証されている`backend/tests/`のみを
    ベースラインの対象にした。
    """
    if not _TESTS_DIR.is_dir():
        return BaselineResult(passed=False, summary="backend/tests/ が見つからない", return_code=None)

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pytest", "tests/", "-q",
            cwd=str(_BACKEND_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except (OSError, asyncio.TimeoutError) as exc:
        logger.exception("static_verification_runner: baseline pytest invocation failed")
        return BaselineResult(passed=False, summary=f"pytest実行に失敗: {exc}", return_code=None)

    output = stdout.decode("utf-8", errors="replace")
    # pytestの最終行("16 passed in 0.12s"等)だけを要約として残す——標準
    # 出力全体を保存すると肥大化するため(details_for_persistenceの慣習
    # と同じ、簡潔な要約のみをDBへ残す判断)。
    summary_line = next((line for line in reversed(output.strip().splitlines()) if line.strip()), output[-300:])
    return BaselineResult(passed=proc.returncode == 0, summary=summary_line.strip(), return_code=proc.returncode)


def build_test_coverage_index() -> dict[str, list[str]]:
    """backend/tests/配下の全*.pyファイルを読み取り専用でスキャンし、
    モジュールベース名→そのモジュールをimportしているテストファイルの
    相対パス、という索引を作る。ファイル内容の変更は一切行わない。"""
    index: dict[str, list[str]] = {}
    if not _TESTS_DIR.is_dir():
        return index

    for path in sorted(_TESTS_DIR.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        rel_path = str(path.relative_to(_BACKEND_ROOT))
        for module in parse_imported_app_modules(source):
            index.setdefault(module, []).append(rel_path)
    return index


def _latest_run_normal_track(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """get_recent_prioritization_run()が返す、複数run分が混在しうる行
    リストから、最新のrun_atに属する行だけを取り出し、track="normal"
    (requires_special_reviewだった仮説は、D-3の時点で既にこのtrackから
    構造的に除外されているが、依頼書「明確に除外すること」を徹底する
    ため、ここでも防御的に再確認する)に絞り込む。呼び出し元の
    get_recent_prioritization_run()が既にrun_at降順・priority_rank昇順
    で返しているため、追加のソートは行わない。"""
    if not rows:
        return []
    latest_run_at = rows[0].get("run_at")
    same_run = [r for r in rows if r.get("run_at") == latest_run_at]
    normal_only = [r for r in same_run if r.get("track") == "normal" and r.get("phase_e_handoff")]
    return normal_only[:limit]


async def run_static_verification(*, limit: int = _DEFAULT_LIMIT) -> dict[str, Any]:
    """D-3の直近の優先順位付け結果から、track="normal"の上位limit件を
    対象に、静的検証を行う。仮説が1件も無い場合は空の結果を返す
    (fail-open)。"""
    baseline = await run_baseline_test_suite()
    coverage_index = build_test_coverage_index()

    priority_rows = await get_recent_prioritization_run(limit=200)
    candidates = _latest_run_normal_track(priority_rows, limit=limit)

    results = []
    for row in candidates:
        # phase_e_handoffには、D-3が既に組み立てたhypothesis_id・title・
        # source_evidence等が入っている。static_verification.py側の
        # assess_hypothesis()はこのペイロードにpriorities行自身のid
        # ("hypothesis_priority_id"として使う)も必要とするため、ここで
        # 合成する。
        handoff = dict(row["phase_e_handoff"])
        handoff["id"] = row.get("id")
        result = assess_hypothesis(handoff, coverage_index=coverage_index, baseline=baseline)
        results.append(result)

    verdict_counts: dict[str, int] = {}
    for r in results:
        verdict_counts[r.verdict] = verdict_counts.get(r.verdict, 0) + 1

    return {
        "baseline": asdict(baseline),
        "candidates_considered": len(candidates),
        "verdict_counts": verdict_counts,
        "results": [asdict(r) for r in results],
    }
