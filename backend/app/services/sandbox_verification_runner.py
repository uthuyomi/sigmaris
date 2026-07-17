# 役割: Phase E-2「別ポートでの動的検証」のオーケストレーション(subprocess
# 起動・停止・HTTPポーリング・既存ヘルスチェック関数の呼び出し)。
#
# 【最重要・繰り返し明記】起動するのは、現在の(一切変更していない)
# Sigmarisのコードそのものである。仮説の内容をコードへ適用する処理は
# 一切行わない——本パイプラインが読むのは、E-1(sigmaris_static_
# verifications)の"insufficient_signal"判定の一覧(どの仮説が、この
# サンドボックス基盤による将来の手動動的検証の候補になるか、という
# 参考情報としてのみ)であり、その仮説の`title`/`how_to_improve`等の
# 内容は、本パイプラインのどの関数にも一切渡されない。
#
# 【安全設計の要点】
#   1. 本番ポート(8000)での起動を、コードレベルで拒否する(sandbox_
#      verification.pyのFORBIDDEN_PRODUCTION_PORT)
#   2. 127.0.0.1(ループバックのみ)でbindし、LAN/Tailscaleから
#      到達不能にする
#   3. 外部副作用のある機能(X投稿・プロアクティブ通知・ヘルスケア同期・
#      リサーチエージェント)を、環境変数で強制的に無効化する
#      (オペレーターの実際の.env設定に関わらず)
#   4. C-full-1のbench_auth.py(専用Supabase認証アカウント)をそのまま
#      再利用し、本番の記憶データには一切アクセスしない
#   5. 起動から一定時間で必ず終了する(セッション全体をタイムアウトで
#      包み、try/finallyでsubprocessの終了を保証する。terminate()で
#      応答が無ければkill()で強制終了する二段構え)

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import httpx

from app.services.bench_auth import BenchAuthError, get_eval_bench_jwt
from app.services.sandbox_verification import (
    FORBIDDEN_PRODUCTION_PORT,
    SANDBOX_BIND_HOST,
    HealthCheckOutcome,
    SandboxVerificationResult,
    build_sandbox_env,
)
from app.services.static_verification_store import get_recent_static_verifications

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_PORT = 8001
_DEFAULT_SESSION_TIMEOUT_SECONDS = 300.0  # 5分(依頼書が例示した5〜10分の下限)
_DEFAULT_STARTUP_TIMEOUT_SECONDS = 30.0
_STARTUP_POLL_INTERVAL_SECONDS = 0.5
_SHUTDOWN_GRACE_SECONDS = 5.0


async def _wait_until_ready(port: int, *, timeout_seconds: float) -> bool:
    """/healthに200が返るまでポーリングする。timeout_seconds以内に
    起動しなければFalseを返す(例外は投げない、fail-open)。"""
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    url = f"http://{SANDBOX_BIND_HOST}:{port}/health"
    async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(_STARTUP_POLL_INTERVAL_SECONDS)
    return False


async def _run_lightweight_health_checks(port: int) -> list[HealthCheckOutcome]:
    """既存の軽量なヘルスチェック(RC指標・Grounding指標)を、bench
    アカウントのJWTで呼び出す。C-mini(run_eval)は、生成済みtestset
    (backend/eval/testset.json、通常は本番アカウントの実データから
    生成される)を前提にしており、空のbenchアカウントでは意味のある
    testsetを持てないため、本タスクでは対象外とした(判断根拠、
    レポート9章参照)。

    【重要な限界、正直に記録する】RC指標(cycle_health_runner.run_
    cycle_health())・Grounding指標(grounding_health_runner.run_
    grounding_health())が実際に読むテーブルの一部(sigmaris_experience・
    sigmaris_cycle_health_runs・sigmaris_grounding_health_runs・
    sigmaris_decision_log等)は、そもそもuser_id列を持たない、単一
    テナント前提のグローバルなテーブルである(Phase R/G自体の既存設計)。
    そのため、benchのJWTを渡しても、これらのテーブルへの読み取りは
    実際には本番の測定履歴を読むことになる——C-full-1のuser_fact_items
    (user_idスコープ・RLS分離)とは異なる。この関数は読み取り専用
    (record_*_run()は一切呼ばない)であり、本番データを変更する心配は
    無いが、「完全にbench分離されたデータで計算している」とは言えない
    ことを、結果を解釈する際の前提として明記する。ここで確認したいのは
    あくまで「サンドボックスプロセスから、これらの関数を呼び出しても
    未処理の例外で落ちないか」であり、計算結果の値自体は保存しない。
    """
    from app.services.cycle_health_runner import run_cycle_health
    from app.services.grounding_health_runner import run_grounding_health

    outcomes: list[HealthCheckOutcome] = []

    try:
        bench_jwt = await get_eval_bench_jwt()
    except BenchAuthError as exc:
        logger.warning("sandbox_verification_runner: bench account not configured, skipping health checks")
        return [
            HealthCheckOutcome(name="cycle_health", status="skipped", detail=str(exc)),
            HealthCheckOutcome(name="grounding_health", status="skipped", detail=str(exc)),
        ]

    try:
        await run_cycle_health(jwt=bench_jwt, window_days=7)
        outcomes.append(HealthCheckOutcome(name="cycle_health", status="ok"))
    except Exception as exc:  # noqa: BLE001 -- 依頼書「エラーを詳細に記録し、絶対に黙殺しない」への対応
        logger.exception("sandbox_verification_runner: cycle_health check raised")
        outcomes.append(HealthCheckOutcome(name="cycle_health", status="error", detail=repr(exc)))

    try:
        await run_grounding_health(jwt=bench_jwt, window_days=7)
        outcomes.append(HealthCheckOutcome(name="grounding_health", status="ok"))
    except Exception as exc:  # noqa: BLE001
        logger.exception("sandbox_verification_runner: grounding_health check raised")
        outcomes.append(HealthCheckOutcome(name="grounding_health", status="error", detail=repr(exc)))

    return outcomes


async def _get_candidate_hypothesis_ids(*, limit: int = 50) -> list[str]:
    """E-1が"insufficient_signal"と判定した(=静的検証だけでは判断材料が
    無かった)仮説のidを、直近の実行から取得する。これらが、今回の
    サンドボックス基盤検証が「将来役立ちうる」候補として記録される
    仮説群である——ただし、この関数はidを取得するだけで、仮説の内容
    (title/how_to_improve等)は一切読まない。"""
    rows = await get_recent_static_verifications(limit=limit)
    return [
        str(r["hypothesis_id"])
        for r in rows
        if r.get("verdict") == "insufficient_signal" and r.get("hypothesis_id")
    ]


async def _terminate_process(proc: asyncio.subprocess.Process) -> bool:
    """依頼書「確実に、自動的に停止する」への対応。terminate()(緩やかな
    停止要求)→短い猶予→応答が無ければkill()(強制終了)という二段構え。
    戻り値は、最終的にプロセスが終了したか(Trueなら確実に停止済み)。"""
    if proc.returncode is not None:
        return True
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
        return True
    except (ProcessLookupError, asyncio.TimeoutError):
        pass
    try:
        if proc.returncode is None:
            proc.kill()
            await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
        return True
    except (ProcessLookupError, asyncio.TimeoutError):
        logger.error("sandbox_verification_runner: failed to confirm subprocess termination")
        return proc.returncode is not None


async def run_sandbox_verification(
    *,
    port: int = _DEFAULT_PORT,
    session_timeout_seconds: float = _DEFAULT_SESSION_TIMEOUT_SECONDS,
    startup_timeout_seconds: float = _DEFAULT_STARTUP_TIMEOUT_SECONDS,
) -> SandboxVerificationResult:
    """サンドボックスを起動し、軽量なヘルスチェックを行い、必ず停止する。

    判断根拠(セッション全体をasyncio.wait_forで包む理由): 個々の
    ヘルスチェック関数がハングした場合でも、外側のタイムアウトが
    セッション全体を打ち切る、二重の安全網にした——内側(起動待ちの
    タイムアウト)・外側(セッション全体のタイムアウト)のいずれが
    働いても、必ずtry/finallyのプロセス終了処理を通過する。
    """
    if port == FORBIDDEN_PRODUCTION_PORT:
        raise ValueError(f"サンドボックスを本番ポート({FORBIDDEN_PRODUCTION_PORT})で起動することは禁止されています。")

    env = build_sandbox_env(port=port)
    candidate_ids = await _get_candidate_hypothesis_ids()

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", str(port),
        cwd=str(_BACKEND_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    started = False
    startup_detail = ""
    health_checks: list[HealthCheckOutcome] = []
    terminated_cleanly = False

    try:
        async def _session() -> None:
            nonlocal started, startup_detail, health_checks
            started = await _wait_until_ready(port, timeout_seconds=startup_timeout_seconds)
            if not started:
                startup_detail = f"{startup_timeout_seconds}秒以内に/healthが200を返さなかった"
                return
            startup_detail = "起動確認OK(/healthが200を返した)"
            health_checks = await _run_lightweight_health_checks(port)

        await asyncio.wait_for(_session(), timeout=session_timeout_seconds)
    except asyncio.TimeoutError:
        startup_detail = startup_detail or f"セッション全体のタイムアウト({session_timeout_seconds}秒)に到達した"
        logger.warning("sandbox_verification_runner: session timed out, terminating sandbox process")
    except Exception:
        logger.exception("sandbox_verification_runner: unexpected error during sandbox session")
        startup_detail = startup_detail or "セッション中に予期しない例外が発生した"
    finally:
        terminated_cleanly = await _terminate_process(proc)

    return SandboxVerificationResult(
        port=port,
        started=started,
        startup_detail=startup_detail,
        health_checks=health_checks,
        candidate_hypothesis_ids=candidate_ids,
        terminated_cleanly=terminated_cleanly,
    )
