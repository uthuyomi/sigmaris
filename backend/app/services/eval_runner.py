# 役割: Phase C-mini「最小評価基盤」+ Phase C-full SB-3のオーケストレーション。
#
# backend/eval/testset.json を読み込み、実際に本番と同じ検索経路
# (memory_search.search_relevant_memories — Phase A5でLOCAL_LLM_ENABLEDに
# よらず機能するよう修正済み)にかけてmemory_f1_score/rag_ndcg_scoreを、
# agent_invocation_audit_logsの集計でresponse_error_rateを算出する。
# Phase C-full-2でmemory_duplicate_rate(SB-3)も同じ実行の中で算出する
# (docs/sigmaris/phase_c_full_report.md参照)。
#
# 【重要】これらは内部テストセットに基づく社内指標であり、対外的な客観
# ベンチマーク(LongMemEval/LoCoMo等)ではない。Phase B群の各機能の効果を
# 「前回計測との差分」として素早く把握する目的に限定して使うこと。

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.eval_metrics import (
    RetrievalResult,
    aggregate_retrieval_scores,
    compute_memory_duplicate_rate,
    compute_response_error_rate,
)
from app.services.memory_search import search_relevant_memories
from app.services.supabase_rest import rest_select
from app.services.user_fact_data import get_fact_items, get_fact_items_with_embeddings

logger = logging.getLogger(__name__)


async def _fetch_recent_audit_statuses(jwt: str, user_id: str, *, days: int) -> list[str]:
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    rows = await rest_select(
        jwt,
        "agent_invocation_audit_logs",
        {
            "select": "status",
            "user_id": f"eq.{user_id}",
            "created_at": f"gte.{since}",
        },
    )
    if not isinstance(rows, list):
        return []
    return [row.get("status") for row in rows if isinstance(row.get("status"), str)]


async def run_eval(
    *,
    jwt: str,
    user_id: str,
    testset: dict[str, Any],
    search_limit: int = 5,
    error_window_days: int = 7,
) -> dict[str, Any]:
    """Run the 3 Phase C-mini metrics + SB-3 (memory_duplicate_rate) against
    a loaded testset dict (backend/eval/testset.json's parsed contents)."""
    entries = testset.get("entries", [])

    # fact_items (no embedding, BA2-trimmed) is used for the retrieval
    # scoring key_to_id map below; fact_items_with_embeddings (a separate
    # fetch — see that function's docstring for why it can't reuse the same
    # BA2-trimmed select) is only for SB-3's duplicate clustering. Run
    # concurrently since they're independent reads.
    fact_items, fact_items_with_embeddings = await asyncio.gather(
        get_fact_items(jwt, active_only=True),
        get_fact_items_with_embeddings(jwt, active_only=True),
    )
    key_to_id = {
        f"{item.get('category')}/{item.get('key')}": item["id"]
        for item in fact_items
        if item.get("id")
    }

    retrieval_results: list[RetrievalResult] = []
    skipped_entry_ids: list[str] = []

    for entry in entries:
        expected_ids = {
            key_to_id[key] for key in entry.get("expected_fact_keys", []) if key in key_to_id
        }
        if not expected_ids:
            # 正解となるfactが現在の生きたuser_fact_itemsに1件も見つからない
            # (削除された/keyが変わった等)。採点不能なので除外し、後で報告する。
            skipped_entry_ids.append(entry["id"])
            continue

        rows = await search_relevant_memories(
            entry["question"], user_id, limit=search_limit, jwt=jwt
        )
        retrieved_ids = [row["id"] for row in rows if row.get("id")]
        retrieval_results.append(
            RetrievalResult(
                query_id=entry["id"], retrieved_ids=retrieved_ids, relevant_ids=expected_ids
            )
        )

    aggregate = aggregate_retrieval_scores(retrieval_results, k=search_limit)

    statuses = await _fetch_recent_audit_statuses(jwt, user_id, days=error_window_days)
    error_rate, sample_size = compute_response_error_rate(statuses)

    duplicate_result = compute_memory_duplicate_rate(fact_items_with_embeddings)

    return {
        "run_at": datetime.now(UTC).isoformat(),
        "testset_version": testset.get("generated_at"),
        "testset_size": len(entries),
        "evaluated_count": aggregate.query_count,
        "skipped_entry_ids": skipped_entry_ids,
        "memory_precision": aggregate.memory_precision,
        "memory_recall": aggregate.memory_recall,
        "memory_f1_score": aggregate.memory_f1_score,
        "rag_ndcg_score": aggregate.rag_ndcg_score,
        "response_error_rate": error_rate,
        "response_sample_size": sample_size,
        "response_error_window_days": error_window_days,
        "memory_duplicate_rate": duplicate_result.memory_duplicate_rate,
        "duplicate_total_facts": duplicate_result.total_facts,
        "duplicate_facts_with_embedding": duplicate_result.facts_with_embedding,
        "duplicate_fact_count": duplicate_result.duplicate_fact_count,
        "duplicate_cluster_count": duplicate_result.duplicate_cluster_count,
        "duplicate_clusters": [
            {"fact_ids": c.fact_ids, "max_similarity": c.max_similarity} for c in duplicate_result.clusters
        ],
        "per_query": aggregate.per_query,
    }
