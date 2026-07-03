# 役割: Phase C-mini「最小評価基盤」の純粋な指標計算ロジック。
#
# 【重要】この指標群は客観的な外部ベンチマーク(LongMemEval/LoCoMo等)ではなく、
# シグマリス自身のデータから生成した内部テストセットに基づく社内指標である。
# Phase B群の各機能実装の効果を「前回の計測との差分」として素早く把握するための
# ものであり、対外的に「業界水準比でこの精度」と主張する根拠にはならない。
# (docs/sigmaris/phase_c_mini_report.md の「重要な前提」参照)
#
# I/Oを一切持たない純粋関数のみを置く。DB・LLM呼び出しはeval_runner.py側の責務。

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class RetrievalResult:
    """1つのテストセット問に対する検索結果と正解の対応。"""

    query_id: str
    retrieved_ids: list[str]  # 類似度順（search_relevant_memoriesの返り値順）
    relevant_ids: set[str]  # 正解として期待されるfact item id集合


@dataclass
class RetrievalScores:
    precision: float
    recall: float
    f1: float
    ndcg: float


def score_retrieval(result: RetrievalResult, *, k: int | None = None) -> RetrievalScores:
    """1問分のPrecision/Recall/F1/NDCGを計算する。"""
    retrieved = result.retrieved_ids[:k] if k is not None else result.retrieved_ids
    precision, recall, f1 = _precision_recall_f1(retrieved, result.relevant_ids)
    ndcg = _ndcg(retrieved, result.relevant_ids)
    return RetrievalScores(precision=precision, recall=recall, f1=f1, ndcg=ndcg)


def _precision_recall_f1(
    retrieved_ids: list[str], relevant_ids: set[str]
) -> tuple[float, float, float]:
    retrieved_set = set(retrieved_ids)

    if not relevant_ids:
        # 正解が定義されていない問い(テストセットの不備)。何も返さなければ
        # 「害はなかった」とみなし満点、何か返せば正解不明のため0点とする。
        return (1.0, 1.0, 1.0) if not retrieved_set else (0.0, 0.0, 0.0)

    if not retrieved_set:
        return 0.0, 0.0, 0.0

    true_positives = len(retrieved_set & relevant_ids)
    precision = true_positives / len(retrieved_set)
    recall = true_positives / len(relevant_ids)
    f1 = 0.0 if (precision + recall) == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def _ndcg(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """二値関連度(0/1)によるNDCG。全ての正解を同等の関連度として扱う
    (指示書の「全て同等でよい」を採用。判断根拠はレポート参照)。"""
    dcg = sum(
        (1.0 if doc_id in relevant_ids else 0.0) / math.log2(index + 2)
        for index, doc_id in enumerate(retrieved_ids)
    )
    ideal_hit_count = min(len(relevant_ids), len(retrieved_ids)) if retrieved_ids else len(relevant_ids)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hit_count))

    if idcg == 0.0:
        return 1.0 if not retrieved_ids else 0.0

    return dcg / idcg


@dataclass
class AggregateRetrievalScores:
    memory_precision: float
    memory_recall: float
    memory_f1_score: float
    rag_ndcg_score: float
    query_count: int
    per_query: list[dict] = field(default_factory=list)


def aggregate_retrieval_scores(
    results: list[RetrievalResult], *, k: int | None = None
) -> AggregateRetrievalScores:
    """テストセット全体の平均を取る(マクロ平均: 問ごとに1票、正解件数の多寡で
    重み付けしない)。"""
    if not results:
        return AggregateRetrievalScores(0.0, 0.0, 0.0, 0.0, 0, [])

    per_query: list[dict] = []
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    ndcgs: list[float] = []

    for result in results:
        scores = score_retrieval(result, k=k)
        precisions.append(scores.precision)
        recalls.append(scores.recall)
        f1s.append(scores.f1)
        ndcgs.append(scores.ndcg)
        per_query.append(
            {
                "query_id": result.query_id,
                "precision": scores.precision,
                "recall": scores.recall,
                "f1": scores.f1,
                "ndcg": scores.ndcg,
                "retrieved_count": len(result.retrieved_ids),
                "relevant_count": len(result.relevant_ids),
            }
        )

    n = len(results)
    return AggregateRetrievalScores(
        memory_precision=sum(precisions) / n,
        memory_recall=sum(recalls) / n,
        memory_f1_score=sum(f1s) / n,
        rag_ndcg_score=sum(ndcgs) / n,
        query_count=n,
        per_query=per_query,
    )


def compute_response_error_rate(
    statuses: list[str], *, error_statuses: frozenset[str] = frozenset({"failed"})
) -> tuple[float, int]:
    """agent_invocation_audit_logsのstatus列の集計。'failed'のみをエラーとして
    扱う('completed_with_fallback'はフォールバックはしたが応答は返せているため、
    完全な失敗とは区別する。判断根拠はレポート参照)。

    戻り値: (error_rate, sample_size)。sample_size=0のときerror_rateは0.0。
    """
    total = len(statuses)
    if total == 0:
        return 0.0, 0
    error_count = sum(1 for status in statuses if status in error_statuses)
    return error_count / total, total
