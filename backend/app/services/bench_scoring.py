from __future__ import annotations

# 役割: Phase C-full ベンチマーク結果の集計。eval_metrics.py と同じく
# I/Oを一切持たない純粋関数のみを置く(DB・LLM呼び出しはbench_pipeline.py/
# CLIスクリプト側の責務)。

from dataclasses import dataclass, field

from app.services.bench_pipeline import QuestionResult


@dataclass
class BenchScoreSummary:
    dataset: str
    total_questions: int
    correct_count: int
    overall_accuracy: float
    category_counts: dict[str, int]
    category_correct: dict[str, int]
    category_accuracy: dict[str, float]
    adversarial_accuracy: float | None  # None if no adversarial questions were scored
    per_question: list[dict] = field(default_factory=list)


def aggregate_bench_results(results: list[QuestionResult], *, dataset: str) -> BenchScoreSummary:
    """Overall + per-category accuracy over a list of QuestionResult.

    Accuracy is a simple mean over questions (not macro-averaged per
    instance) — unlike C-mini's memory_f1_score (which macro-averages per
    query so a handful of huge test cases can't dominate), LongMemEval/
    LoCoMo's own published methodology reports per-question accuracy
    directly, and this needs to stay comparable to those published numbers
    (the whole point of Phase C-full, see docs/sigmaris/
    phase_c_full_report.md section 1) rather than deviate for consistency
    with C-mini's unrelated internal metric.
    """
    total = len(results)
    if total == 0:
        return BenchScoreSummary(
            dataset=dataset,
            total_questions=0,
            correct_count=0,
            overall_accuracy=0.0,
            category_counts={},
            category_correct={},
            category_accuracy={},
            adversarial_accuracy=None,
            per_question=[],
        )

    category_counts: dict[str, int] = {}
    category_correct: dict[str, int] = {}
    adversarial_total = 0
    adversarial_correct = 0
    correct_count = 0
    per_question: list[dict] = []

    for result in results:
        category_counts[result.category] = category_counts.get(result.category, 0) + 1
        if result.correct:
            correct_count += 1
            category_correct[result.category] = category_correct.get(result.category, 0) + 1
        if result.is_adversarial:
            adversarial_total += 1
            if result.correct:
                adversarial_correct += 1
        per_question.append(
            {
                "instance_id": result.instance_id,
                "question_id": result.question_id,
                "category": result.category,
                "is_adversarial": result.is_adversarial,
                "correct": result.correct,
                "retrieved_count": result.retrieved_count,
                "judge_reasoning": result.judge_reasoning,
            }
        )

    category_accuracy = {
        category: category_correct.get(category, 0) / count
        for category, count in category_counts.items()
    }

    return BenchScoreSummary(
        dataset=dataset,
        total_questions=total,
        correct_count=correct_count,
        overall_accuracy=correct_count / total,
        category_counts=category_counts,
        category_correct=category_correct,
        category_accuracy=category_accuracy,
        adversarial_accuracy=(adversarial_correct / adversarial_total) if adversarial_total else None,
        per_question=per_question,
    )
