# 役割: Phase C-mini「最小評価基盤」+ Phase C-full SB-3(記憶重複率)の
# 純粋な指標計算ロジック。
#
# 【重要】この指標群は客観的な外部ベンチマーク(LongMemEval/LoCoMo等)ではなく、
# シグマリス自身のデータから生成した内部テストセットに基づく社内指標である。
# Phase B群の各機能実装の効果を「前回の計測との差分」として素早く把握するための
# ものであり、対外的に「業界水準比でこの精度」と主張する根拠にはならない。
# (docs/sigmaris/phase_c_mini_report.md の「重要な前提」参照)
#
# I/Oを一切持たない純粋関数のみを置く。DB・LLM呼び出しはeval_runner.py側の責務。

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any


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


# ─── Phase C-full SB-3: memory_duplicate_rate ─────────────────────────────────
#
# 「同じ内容が表現を変えて複数回登録されている状態」(docs/sigmaris/
# phase_c_full_report.md 参照)をどう検出するか: user_fact_itemsは
# (user_id, category, key) にUNIQUE制約があるため、同一category/keyの
# 行が2つ存在することはあり得ない — ここで言う「重複」は、**異なる
# category/keyの行が、実質的に同じ主張をしている**状態を指す(例:
# 抽出時の判断揺れで、あるターンではcategory=preferences/key=favorite_
# color、別のターンではcategory=lifestyle/key=color_preferenceとして、
# 同じ「好きな色」という事実が別々の行に記録されてしまうケース)。
#
# 判定には、B1(ハイブリッド検索)が既に生成・保存しているベクトル
# embedding(user_fact_items.embedding、pgvector 768次元)をそのまま流用
# する。search_fact_memory RPC自体は「1つのクエリベクトル vs コーパス」
# の形にしか対応していないため直接は使えないが、そのRPCが使っている
# 類似度の定義(`1 - cosine_distance` = 標準的なコサイン類似度、
# 202607150037_time_aware_search.sql参照)を、全ペア(コーパス vs
# コーパス自身)に適用する形でそのまま再利用する。新しい類似度アルゴリズム
# は導入していない。


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """B1のsearch_fact_memory RPCが使う `1 - (embedding <=> query_embedding)`
    と同じ定義(標準コサイン類似度)。pgvectorの `<=>` はコサイン距離な
    ので、これは pgvector 側の計算と数学的に同一の結果を返す。"""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class _UnionFind:
    """重複クラスタ(類似度が閾値以上の事実の連結成分)をまとめるための、
    標準的なUnion-Find。新規の重複検出アルゴリズムではなく、既に計算済み
    のペア単位の類似度(上記_cosine_similarity)を「誰と誰が同じグループ
    か」に集約するための、ごく一般的な補助データ構造。"""

    def __init__(self, ids: list[str]) -> None:
        self._parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


@dataclass
class DuplicateCluster:
    fact_ids: list[str]
    max_similarity: float


@dataclass
class MemoryDuplicateResult:
    memory_duplicate_rate: float
    total_facts: int
    facts_with_embedding: int
    duplicate_fact_count: int  # 「完全に重複排除したら削除される件数」(下記rate算出式の分子)
    duplicate_cluster_count: int
    clusters: list[DuplicateCluster] = field(default_factory=list)


# search_fact_memory RPC(B1)のデフォルトmatch_threshold(0.7)は「このクエリ
# に無関係ではない」という緩い関連性の基準であり、「これは同じ事実の言い
# 換えだ」という、はるかに厳しい基準には流用できない(0.7では、話題が近い
# だけの別々の事実まで大量に「重複」と誤検出してしまう)。0.92は、言い換え
# (パラフレーズ)は意味的にほぼ完全に重なる一方、単に話題が近いだけの事実
# 同士はここまでは上がらない、という直感に基づく値であり、実LLM/embedding
# 環境での実測による検証はできていない(0章参照)。誤検出(実際には別の事実
# なのに重複と判定してしまう)より見逃し(実際には重複なのに検出できない)
# を許容する、安全側に倒した選択。
DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD = 0.92


def compute_memory_duplicate_rate(
    items: list[dict[str, Any]],
    *,
    similarity_threshold: float = DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD,
) -> MemoryDuplicateResult:
    """SB-3 (memory_duplicate_rate) の算出。

    items: 各要素は {"id": str, "embedding": list[float] | None, ...}
    (user_fact_data.get_fact_items_with_embeddings()の戻り値をそのまま
    渡せる形)。embeddingがNone/空の項目は、コサイン類似度を計算しようが
    ないため重複判定の対象から除外する(= 重複なしとみなす、安全側に倒す
    判断 — facts_with_embeddingで除外件数を可視化する)。

    算出式: 類似度がsimilarity_threshold以上の事実どうしを辺として連結成分
    (クラスタ)を作り、
        memory_duplicate_rate = Σ(クラスタサイズ - 1 のうちサイズ>=2のもの) / total_facts
    とする。「全記憶に対する重複ペアの割合」ではなく、この「完全に重複排除
    した場合に削除される件数の割合」を採用した判断根拠: 3件が相互に重複し
    ている場合、ペア単位(3ペア)で数えると重複が実態より多く見え、閾値
    (roadmap記載の目標3%以下)との対比が歪む。「このクラスタから1件だけ
    残せば済む」という記憶の無駄(2件が不要)を数える方が、「重複してい
    る記憶を削除すればどれだけ減らせるか」という指標の意図に近いと判断した。
    分母は`total_facts`(embeddingの有無を問わない全アクティブ事実数)とし、
    embedding未生成分もそのまま母数に含める(B1のupdate_fact_embeddings()
    でバックフィルが完了していない状態では、実際より低い値が出る=安全側の
    バイアスであることを明記する)。
    """
    total_facts = len(items)
    with_embedding: list[dict[str, Any]] = []
    for item in items:
        embedding = item.get("embedding")
        if isinstance(embedding, str):
            try:
                embedding = json.loads(embedding)
            except (ValueError, TypeError):
                embedding = None
        if isinstance(embedding, list) and embedding and item.get("id"):
            with_embedding.append({"id": str(item["id"]), "embedding": [float(v) for v in embedding]})

    if total_facts == 0 or len(with_embedding) < 2:
        return MemoryDuplicateResult(
            memory_duplicate_rate=0.0,
            total_facts=total_facts,
            facts_with_embedding=len(with_embedding),
            duplicate_fact_count=0,
            duplicate_cluster_count=0,
            clusters=[],
        )

    ids = [item["id"] for item in with_embedding]
    uf = _UnionFind(ids)
    pair_similarity: dict[str, float] = {}  # union-find root -> max similarity seen in its cluster so far

    for i in range(len(with_embedding)):
        for j in range(i + 1, len(with_embedding)):
            sim = _cosine_similarity(with_embedding[i]["embedding"], with_embedding[j]["embedding"])
            if sim >= similarity_threshold:
                uf.union(with_embedding[i]["id"], with_embedding[j]["id"])
                root = uf.find(with_embedding[i]["id"])
                pair_similarity[root] = max(pair_similarity.get(root, 0.0), sim)

    members_by_root: dict[str, list[str]] = {}
    for fact_id in ids:
        root = uf.find(fact_id)
        members_by_root.setdefault(root, []).append(fact_id)

    clusters = [
        DuplicateCluster(fact_ids=sorted(members), max_similarity=pair_similarity.get(root, 0.0))
        for root, members in members_by_root.items()
        if len(members) >= 2
    ]
    clusters.sort(key=lambda c: c.max_similarity, reverse=True)

    duplicate_fact_count = sum(len(c.fact_ids) - 1 for c in clusters)
    rate = duplicate_fact_count / total_facts if total_facts else 0.0

    return MemoryDuplicateResult(
        memory_duplicate_rate=rate,
        total_facts=total_facts,
        facts_with_embedding=len(with_embedding),
        duplicate_fact_count=duplicate_fact_count,
        duplicate_cluster_count=len(clusters),
        clusters=clusters,
    )
