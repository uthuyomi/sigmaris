from __future__ import annotations

# 役割: Phase C-full(LongMemEval/LoCoMo)の実行本体 — 記憶パイプラインへの
# 投入、質問応答、LLM-as-a-Judge採点をオーケストレーションする。
#
# 【重要】本番の記憶パイプライン(memory_extractor.extract_from_conversation・
# memory_search.search_relevant_memories)をそのまま呼び出す。ここで独自の
# 抽出・検索ロジックを再実装することはしない — さもないと「シグマリスの
# 記憶パイプラインの評価」ではなく「別物の評価」になってしまう。
# 分離のための専用ユーザーはbench_auth.pyが担う。

import json
import logging
from dataclasses import dataclass

from app.services.bench_auth import wipe_bench_user_fact_items
from app.services.bench_common import BenchInstance, BenchQuestion
from app.services.local_llm import TaskType, get_llm_router
from app.services.memory_extractor import extract_from_conversation
from app.services.memory_search import search_relevant_memories

logger = logging.getLogger(__name__)

# memory_extractor._format_conversation() only looks at messages[-20:] (and
# truncates each message to 500 chars) — a LongMemEval/LoCoMo session that
# exceeds this would silently lose its earlier turns to extraction. Chunking
# at 16 (a small margin under 20) keeps every chunk within that window
# regardless of how ingest_instance() batches sessions.
_INGEST_CHUNK_SIZE = 16

_ANSWER_SYSTEM = (
    "You are a memory-recall question answering system being evaluated on "
    "a long-term memory benchmark. Given a set of facts retrieved from "
    "long-term memory and a question, answer concisely and factually using "
    "only those retrieved facts. Never use outside knowledge to fill in "
    "gaps. If the facts do not contain enough information to answer, say "
    "so explicitly rather than guessing."
)

_ANSWER_PROMPT = """Retrieved facts (from long-term memory, similarity-ranked):
{context}

Reference date for relative-time questions: {question_date}

Question: {question}

Answer in one short sentence, using only the retrieved facts above. If the \
facts are insufficient to answer, say "I don't have enough information to \
answer that." rather than guessing."""

_JUDGE_SYSTEM = (
    "You are an expert grader for a long-term-memory question-answering "
    "benchmark (LongMemEval / LoCoMo). Compare a system's generated answer "
    "against the gold answer and judge whether the generated answer is "
    "correct. Be lenient about phrasing, format, and minor wording "
    "differences (e.g. \"May 7, 2023\" and \"2023-05-07\" are the same "
    "answer; \"2022\" and \"in 2022\" are the same answer). Be strict about "
    "factual content — a vague, partial, or hedged answer that omits the "
    "key fact is incorrect. Return valid JSON only."
)

_JUDGE_PROMPT = """Question: {question}
Gold answer: {gold_answer}
Generated answer: {generated_answer}
Is this an adversarial question (the "gold answer" above is actually a \
false premise the question is trying to trick the system into confirming \
— the CORRECT behavior is for the system to decline / say the \
information is not available, NOT to state the gold answer as fact)?: \
{is_adversarial}

Grading rules:
- If this is NOT adversarial: the generated answer is correct if it \
conveys the same factual content as the gold answer, allowing for \
paraphrase and formatting differences.
- If this IS adversarial: the generated answer is correct ONLY if it \
declines to confirm the premise (says the information is not available, \
not mentioned, or expresses uncertainty). If it confidently restates the \
gold answer text as established fact, it is INCORRECT.

Return this exact JSON shape and nothing else:
{{"correct": true or false, "reasoning": "one short sentence explaining the verdict"}}"""


@dataclass
class QuestionResult:
    instance_id: str
    question_id: str
    dataset: str
    category: str
    is_adversarial: bool
    question: str
    gold_answer: str
    generated_answer: str
    retrieved_count: int
    correct: bool
    judge_reasoning: str


def _chunk_messages(
    messages: list[dict[str, str]], size: int
) -> list[list[dict[str, str]]]:
    return [messages[i : i + size] for i in range(0, len(messages), size)]


async def ingest_instance(instance: BenchInstance, *, jwt: str) -> int:
    """Feed this instance's sessions into memory_extractor.py in
    chronological order, session by session (each further chunked to stay
    inside the extractor's own messages[-20:] window — see
    _INGEST_CHUNK_SIZE above). Never raises: extract_from_conversation()
    already swallows its own failures per-call, and a single failed chunk
    should not abort ingesting the rest of the instance. Returns the number
    of extraction calls made (for progress reporting)."""
    chunk_count = 0
    thread_prefix = f"bench:{instance.dataset}:{instance.instance_id}"
    for session in instance.sessions:
        plain_messages = [{"role": m.role, "content": m.content} for m in session.messages]
        for chunk in _chunk_messages(plain_messages, _INGEST_CHUNK_SIZE):
            if not chunk:
                continue
            try:
                await extract_from_conversation(
                    messages=chunk,
                    jwt=jwt,
                    thread_id=f"{thread_prefix}:{session.session_id}",
                )
            except Exception:
                logger.exception(
                    "bench_pipeline: extraction failed instance=%s session=%s",
                    instance.instance_id, session.session_id,
                )
            chunk_count += 1
    return chunk_count


async def synthesize_answer(
    question: BenchQuestion, *, jwt: str, user_id: str, search_limit: int
) -> tuple[str, int]:
    """Retrieve relevant memories (the same hybrid search production chat
    turns use) and synthesize a direct factual answer from them. Returns
    (answer_text, retrieved_count). Never raises — a retrieval or LLM
    failure just produces an empty/apologetic answer, which the judge will
    (correctly) mark wrong rather than crashing the whole run."""
    try:
        rows = await search_relevant_memories(
            question.question, user_id, limit=search_limit, jwt=jwt
        )
    except Exception:
        logger.exception("bench_pipeline: retrieval failed question_id=%s", question.question_id)
        rows = []

    context_lines = [
        f"- {row.get('category') or ''}/{row.get('fact_key') or row.get('key') or ''}: {row.get('value') or ''}"
        for row in rows
    ]
    context = "\n".join(context_lines) if context_lines else "(no relevant facts retrieved)"

    router = get_llm_router()
    try:
        answer = await router.chat(
            TaskType.EVAL_GENERATION,
            [
                {"role": "system", "content": _ANSWER_SYSTEM},
                {"role": "user", "content": _ANSWER_PROMPT.format(
                    context=context,
                    question_date=question.question_date or "unknown",
                    question=question.question,
                )},
            ],
            temperature=0.0,
            max_tokens=200,
        )
    except Exception:
        logger.exception("bench_pipeline: answer synthesis failed question_id=%s", question.question_id)
        answer = ""
    return answer.strip(), len(rows)


async def judge_answer(question: BenchQuestion, generated_answer: str) -> tuple[bool, str]:
    """LLM-as-a-Judge: grade generated_answer against question.gold_answer.
    Never raises — a judge failure is scored as incorrect with a reasoning
    string saying so, rather than crashing the run or (worse) silently
    excluding the question from the denominator."""
    router = get_llm_router()
    try:
        raw = await router.chat(
            TaskType.EVAL_JUDGE,
            [
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": _JUDGE_PROMPT.format(
                    question=question.question,
                    gold_answer=question.gold_answer,
                    generated_answer=generated_answer or "(no answer given)",
                    is_adversarial="yes" if question.is_adversarial else "no",
                )},
            ],
            temperature=0.0,
            max_tokens=300,
            json_mode=True,
        )
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return False, "judge returned non-JSON-object output"
        return bool(parsed.get("correct")), str(parsed.get("reasoning") or "")
    except Exception:
        logger.exception("bench_pipeline: judge call failed question_id=%s", question.question_id)
        return False, "judge call raised an exception"


async def run_instance(
    instance: BenchInstance, *, jwt: str, user_id: str, search_limit: int = 5
) -> list[QuestionResult]:
    """Run one dataset instance end-to-end: wipe -> ingest -> (answer +
    judge) per question. The wipe is what gives each instance a clean
    memory state, isolated both from 海星さん's production data (bench_auth
    resolves a dedicated user_id entirely) and from every *other* instance
    in the same dataset run (bench_auth.wipe_bench_user_fact_items) —
    matching the original benchmarks' own evaluation protocol, where each
    instance's questions are answered against only that instance's own
    sessions."""
    await wipe_bench_user_fact_items(jwt, user_id)
    chunk_count = await ingest_instance(instance, jwt=jwt)
    logger.info(
        "bench_pipeline: ingested instance=%s dataset=%s sessions=%d chunks=%d questions=%d",
        instance.instance_id, instance.dataset, len(instance.sessions), chunk_count, len(instance.questions),
    )

    results: list[QuestionResult] = []
    for question in instance.questions:
        answer, retrieved_count = await synthesize_answer(
            question, jwt=jwt, user_id=user_id, search_limit=search_limit
        )
        correct, reasoning = await judge_answer(question, answer)
        results.append(
            QuestionResult(
                instance_id=instance.instance_id,
                question_id=question.question_id,
                dataset=instance.dataset,
                category=question.category,
                is_adversarial=question.is_adversarial,
                question=question.question,
                gold_answer=question.gold_answer,
                generated_answer=answer,
                retrieved_count=retrieved_count,
                correct=correct,
                judge_reasoning=reasoning,
            )
        )
    return results


async def run_benchmark(
    instances: list[BenchInstance],
    *,
    jwt: str,
    user_id: str,
    search_limit: int = 5,
    on_instance_done=None,
) -> list[QuestionResult]:
    """Shared orchestration for both scripts/run_longmemeval.py and
    scripts/run_locomo.py: run every instance sequentially (never in
    parallel — each run_instance() call wipes the single shared benchmark
    user's memory first, so concurrent instances would corrupt each
    other's isolation) and flatten the results.

    on_instance_done, if given, is called after each instance with
    (instance, results_for_that_instance) — used by the CLI scripts for
    progress output without this function needing to know about stdout.
    """
    all_results: list[QuestionResult] = []
    for instance in instances:
        instance_results = await run_instance(
            instance, jwt=jwt, user_id=user_id, search_limit=search_limit
        )
        all_results.extend(instance_results)
        if on_instance_done is not None:
            on_instance_done(instance, instance_results)
    return all_results
