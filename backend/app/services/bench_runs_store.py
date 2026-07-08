from __future__ import annotations

# 役割: Phase C-full(LongMemEval/LoCoMo)結果の永続化。
#
# sigmaris_eval_runs(Phase C-mini、内部テストセットに基づく社内指標)とは
# 意図的に別テーブル(sigmaris_bench_runs)に記録する。列構成も異なる
# (precision/recall/f1/ndcgではなく、公開ベンチマーク標準のaccuracy+
# カテゴリ別内訳)。同じテーブルに列を追加する形は取らなかった —
# 「社内指標」と「対外的に主張できる客観ベンチマーク」を運用者が一目で
# 区別できることが要件そのものであり(指示書「明確に区別」)、テーブルを
# 分けるのがそれを最も強く保証する形だと判断した。
#
# eval_runs_store.pyと同じ「service_role専用RLS」「書き込み失敗は例外を
# 投げず記録するだけ」パターンを踏襲する。

import logging
from typing import Any

from app.config import settings
from app.services.supabase_rest import _get_client, _require_supabase_config

logger = logging.getLogger(__name__)

_TABLE = "sigmaris_bench_runs"


def _svc_headers() -> dict[str, str]:
    _require_supabase_config()
    key = settings.supabase_service_role_key
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured.")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def record_bench_run(
    *,
    dataset: str,
    dataset_version: str | None,
    instance_count: int,
    total_questions: int,
    correct_count: int,
    overall_accuracy: float,
    category_counts: dict[str, int],
    category_accuracy: dict[str, float],
    adversarial_accuracy: float | None,
    notes: str | None = None,
    details: dict[str, Any] | None = None,
) -> str | None:
    """Insert one benchmark run row. Returns the new row id, or None if
    persistence failed (e.g. migration not applied yet, or
    SUPABASE_SERVICE_ROLE_KEY not configured) — never raises, matching
    eval_runs_store.record_eval_run()'s best-effort semantics: the score
    computation and stdout printout must never depend on this succeeding."""
    try:
        payload: dict[str, Any] = {
            "dataset": dataset,
            "dataset_version": dataset_version,
            "instance_count": instance_count,
            "total_questions": total_questions,
            "correct_count": correct_count,
            "overall_accuracy": overall_accuracy,
            "category_counts": category_counts,
            "category_accuracy": category_accuracy,
            "adversarial_accuracy": adversarial_accuracy,
            "notes": notes,
            "details": details or {},
        }
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.post(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            json=payload,
        )
        response.raise_for_status()
        rows = response.json()
        if isinstance(rows, list) and rows:
            row_id = rows[0].get("id")
            logger.info("bench_runs_store: recorded run id=%s dataset=%s", row_id, dataset)
            return row_id
        return None
    except Exception:
        logger.exception("bench_runs_store: failed to record bench run")
        return None


async def get_recent_bench_runs(dataset: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent runs for one dataset ("longmemeval" |
    "locomo"), newest first. Empty list on any failure (mirrors
    record_bench_run's best-effort semantics)."""
    try:
        base_url, _ = _require_supabase_config()
        client = await _get_client()
        response = await client.get(
            f"{base_url}/rest/v1/{_TABLE}",
            headers=_svc_headers(),
            params={"dataset": f"eq.{dataset}", "order": "run_at.desc", "limit": str(limit)},
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        logger.exception("bench_runs_store: failed to get_recent_bench_runs")
        return []
