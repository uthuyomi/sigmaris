from __future__ import annotations

# 役割: Phase C-full(LongMemEval/LoCoMo)ベンチマーク専用の認証・ユーザー分離。
#
# 【最重要】このモジュールが存在する唯一の理由は、外部データセット
# (架空/他人の会話内容)の取り込み先が、海星さん本人の実際の記憶
# (user_fact_items等)と絶対に混ざらないようにすることである。
# `app.services.proactive.jwt_manager.get_sigmaris_jwt()`(海星さん本人の
# 認証情報)とは完全に別系統の、専用のSupabase Authアカウント
# (SIGMARIS_EVAL_BENCH_REFRESH_TOKEN / SIGMARIS_EVAL_BENCH_USER_JWT)を使う。
#
# セットアップ手順(運用者が事前に1回行う必要がある):
#   1. Supabaseダッシュボード(Authentication → Users)で、ベンチマーク専用の
#      新規ユーザーを作成する(例: sigmaris-eval-bench@example.com のような、
#      海星さん本人のメールアドレスとは異なる使い捨てアドレス)。
#   2. そのユーザーでサインインし(`/auth/v1/token?grant_type=password`)、
#      発行された refresh_token を .env の SIGMARIS_EVAL_BENCH_REFRESH_TOKEN
#      に設定する。
#   3. 本モジュールは初回呼び出し時にこのrefresh_tokenを1回だけ使って
#      access_tokenを取得する(jwt_manager.py のような自動更新・永続化は
#      行わない — バッチスクリプトが1回の実行で使い切る用途のため、
#      Supabaseアクセストークンの標準的な有効期限(通常1時間)で十分)。
#      refresh_tokenを用意できない場合は、静的なSIGMARIS_EVAL_BENCH_USER_JWT
#      をそのまま使うことも可能(有効期限が切れたら手動で取り直す)。

import logging

from app.config import settings
from app.services.proactive.jwt_manager import _do_refresh
from app.services.supabase_rest import get_current_user, rest_delete

logger = logging.getLogger(__name__)


class BenchAuthError(RuntimeError):
    """Raised when the dedicated benchmark account isn't configured, or —
    critically — when it appears to resolve to the same user as the
    production account. Callers must treat this as fatal, not something to
    degrade gracefully from (unlike most other best-effort helpers in this
    codebase): silently falling back to the production JWT here would mean
    writing fictional benchmark conversation content into 海星さん's real
    user_fact_items."""


async def get_eval_bench_jwt() -> str:
    """Resolve an access token for the dedicated benchmark Supabase account.

    Deliberately not a long-lived, auto-refreshing singleton like
    jwt_manager.get_sigmaris_jwt() — this is meant to be called once per
    CLI script invocation (backend/scripts/run_longmemeval.py /
    run_locomo.py), not from a long-running server process, so a single
    token exchange at startup is sufficient for the "small subset" runs
    this phase's scope covers.
    """
    if settings.sigmaris_eval_bench_refresh_token:
        state = await _do_refresh(settings.sigmaris_eval_bench_refresh_token)
        return state.access_token
    if settings.sigmaris_eval_bench_user_jwt:
        return settings.sigmaris_eval_bench_user_jwt
    raise BenchAuthError(
        "Neither SIGMARIS_EVAL_BENCH_REFRESH_TOKEN nor SIGMARIS_EVAL_BENCH_USER_JWT is "
        "configured. A dedicated benchmark Supabase account is required before running "
        "LongMemEval/LoCoMo — see this module's docstring for setup steps. Refusing to "
        "fall back to the production SIGMARIS_REFRESH_TOKEN/SIGMARIS_USER_JWT."
    )


async def resolve_bench_user(jwt: str) -> str:
    """Return the benchmark account's user_id, and refuse to proceed if it
    matches the production account's user_id (belt-and-suspenders check —
    RLS already scopes every write to auth.uid() regardless, but this
    catches a misconfiguration, e.g. SIGMARIS_EVAL_BENCH_REFRESH_TOKEN
    accidentally set to the same value as SIGMARIS_REFRESH_TOKEN, before any
    ingestion happens rather than after)."""
    user = await get_current_user(jwt)
    user_id = user.get("id")
    if not isinstance(user_id, str) or not user_id:
        raise BenchAuthError("Benchmark JWT did not resolve to a valid user id.")

    if settings.sigmaris_refresh_token or settings.sigmaris_user_jwt:
        try:
            from app.services.proactive.jwt_manager import get_sigmaris_jwt  # noqa: PLC0415

            prod_jwt = await get_sigmaris_jwt()
            prod_user = await get_current_user(prod_jwt)
            prod_user_id = prod_user.get("id")
            if isinstance(prod_user_id, str) and prod_user_id == user_id:
                raise BenchAuthError(
                    "The benchmark account resolved to the SAME user_id as the production "
                    "account (SIGMARIS_REFRESH_TOKEN/SIGMARIS_USER_JWT). Refusing to proceed — "
                    "this would mix LongMemEval/LoCoMo conversation content into 海星さん's real "
                    "user_fact_items. Check SIGMARIS_EVAL_BENCH_REFRESH_TOKEN is set to a "
                    "genuinely separate account."
                )
        except BenchAuthError:
            raise
        except Exception:
            # Best-effort cross-check only: if we can't resolve the
            # production identity for comparison (e.g. it's not configured
            # in this environment, or a transient network error), that is
            # not itself evidence of a collision — don't block the run on
            # it. The comparison is a defense-in-depth extra, not the only
            # safety mechanism (RLS is the load-bearing one).
            logger.warning(
                "bench_auth: could not resolve production user_id for the collision check "
                "— continuing without it", exc_info=True,
            )

    logger.info("bench_auth: resolved benchmark user_id=%s", user_id)
    return user_id


async def wipe_bench_user_fact_items(jwt: str, user_id: str) -> None:
    """Hard-delete every user_fact_items row for the benchmark account —
    run between dataset instances (bench_pipeline.run_instance) so each
    LongMemEval/LoCoMo instance's conversation is ingested into a genuinely
    clean memory state, matching the original benchmarks' own evaluation
    protocol (each instance's questions are answered against *only* that
    instance's sessions, never a different instance's).

    Scoped to `user_id=eq.{user_id}` and executed with the benchmark JWT,
    so RLS (auth.uid() = user_id) makes it structurally impossible for this
    to touch any other account's rows even if user_id were wrong — but
    resolve_bench_user()'s check above is what should catch that earlier.
    """
    await rest_delete(jwt, "user_fact_items", {"user_id": f"eq.{user_id}"})
    logger.info("bench_auth: wiped user_fact_items for benchmark user_id=%s", user_id)
