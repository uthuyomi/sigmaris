from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

URL_PATTERN = re.compile(r"https?://[^\s<>()\[\]{}\"']+")
ISO_DATETIME_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T\s]\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?\b"
)
JAPANESE_DATE_PATTERN = re.compile(
    r"(?<!\d)(?:\d{4}年)?\d{1,2}月\d{1,2}日(?:\s*[（(]?[月火水木金土日]曜?日?[）)]?)?"
)
SLASH_DATE_PATTERN = re.compile(r"(?<!\d)\d{1,4}[/-]\d{1,2}[/-]\d{1,4}(?!\d)")
TIME_PATTERN = re.compile(
    r"(?<!\d)(?:午前|午後)?\s*\d{1,2}(?::\d{2}|時(?:\d{1,2}分)?)(?!\d)"
)
COUNT_PATTERN = re.compile(
    r"(?<![\d.])[-+]?\d+(?:[,.]\d+)?\s*(?:件|個|回|人|枚|本|日|時間|分|秒|円|km|m|％|%)(?![\d.])",
    re.IGNORECASE,
)
NUMBER_PATTERN = re.compile(r"(?<![\d.])[-+]?\d+(?:[,.]\d+)?(?![\d.])")

SUCCESS_PATTERNS = (
    re.compile(
        r"(?<!未)(?:成功|完了|登録済み|保存済み|同期済み|登録しました|保存しました|同期しました)"
    ),
    re.compile(r"\b(?:success|succeeded|completed|registered|saved|synced)\b", re.IGNORECASE),
)
FAILURE_PATTERNS = (
    re.compile(
        r"(?:失敗|エラー|未登録|保存されていません|登録できません(?:でした)?|"
        r"保存できません(?:でした)?|同期できません(?:でした)?)"
    ),
    re.compile(r"\b(?:failed|failure|error|not registered|not saved|unsuccessful)\b", re.IGNORECASE),
)
FORBIDDEN_ASSISTANT_NAME_PATTERN = re.compile(
    "|".join(("Shift" + "PilotAI", "shift" + "-pilot-ai", "Shift" + "Pilot"))
)


@dataclass(frozen=True)
class MechanicalGuardResult:
    passed: bool
    violations: tuple[str, ...]


@dataclass(frozen=True)
class ResponseGuardResult:
    passed: bool
    violations: tuple[str, ...]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).rstrip(".,。、)]}")


def _extract_counter(pattern: re.Pattern[str], text: str) -> Counter[str]:
    return Counter(_normalize(match.group(0)) for match in pattern.finditer(text))


def replace_forbidden_assistant_names(text: str) -> str:
    return FORBIDDEN_ASSISTANT_NAME_PATTERN.sub("シグマリス", text)


def _extract_statuses(text: str) -> Counter[str]:
    statuses: Counter[str] = Counter()
    if any(pattern.search(text) for pattern in SUCCESS_PATTERNS):
        statuses["success"] += 1
    if any(pattern.search(text) for pattern in FAILURE_PATTERNS):
        statuses["failure"] += 1
    return statuses


def compare_mechanical_facts(source: str, rewritten: str) -> MechanicalGuardResult:
    source_without_urls = URL_PATTERN.sub("", source)
    rewritten_without_urls = URL_PATTERN.sub("", rewritten)
    comparisons = {
        "URLs": _extract_counter(URL_PATTERN, source) == _extract_counter(URL_PATTERN, rewritten),
        "ISO dates/times": (
            _extract_counter(ISO_DATETIME_PATTERN, source_without_urls)
            == _extract_counter(ISO_DATETIME_PATTERN, rewritten_without_urls)
        ),
        "Japanese dates": (
            _extract_counter(JAPANESE_DATE_PATTERN, source_without_urls)
            == _extract_counter(JAPANESE_DATE_PATTERN, rewritten_without_urls)
        ),
        "slash dates": (
            _extract_counter(SLASH_DATE_PATTERN, source_without_urls)
            == _extract_counter(SLASH_DATE_PATTERN, rewritten_without_urls)
        ),
        "times": (
            _extract_counter(TIME_PATTERN, source_without_urls)
            == _extract_counter(TIME_PATTERN, rewritten_without_urls)
        ),
        "counts": (
            _extract_counter(COUNT_PATTERN, source_without_urls)
            == _extract_counter(COUNT_PATTERN, rewritten_without_urls)
        ),
        "numbers": (
            _extract_counter(NUMBER_PATTERN, source_without_urls)
            == _extract_counter(NUMBER_PATTERN, rewritten_without_urls)
        ),
        "success/failure states": _extract_statuses(source) == _extract_statuses(rewritten),
    }
    violations = tuple(name for name, matched in comparisons.items() if not matched)
    return MechanicalGuardResult(passed=not violations, violations=violations)


def _stringify_tool_payload(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _tool_output_text(tool_events: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for event in tool_events:
        event_type = event.get("type")
        if event_type not in {"tool-output-available", "tool-output-error"}:
            continue
        chunks.append(_stringify_tool_payload(event.get("output")))
    return "\n".join(chunk for chunk in chunks if chunk)


def _tool_response_fact_set(text: str) -> set[str]:
    without_urls = URL_PATTERN.sub("", text)
    facts: set[str] = set()
    for pattern in (
        ISO_DATETIME_PATTERN,
        JAPANESE_DATE_PATTERN,
        SLASH_DATE_PATTERN,
        TIME_PATTERN,
        COUNT_PATTERN,
    ):
        facts.update(_extract_counter(pattern, without_urls).keys())
    for value in _extract_counter(ISO_DATETIME_PATTERN, without_urls):
        date_part = re.split(r"[T\s]", value, maxsplit=1)[0]
        if date_part:
            facts.add(date_part)
        time_match = re.search(r"[T\s](\d{1,2}:\d{2})", value)
        if time_match:
            time_part = time_match.group(1)
            facts.add(time_part)
            if date_part:
                facts.add(_normalize(f"{date_part} {time_part}"))
    return facts


def compare_response_to_tool_outputs(
    *,
    tool_events: list[dict[str, Any]],
    response_text: str,
) -> MechanicalGuardResult:
    """Fast post-generation guard for facts grounded in tool outputs.

    BA4 removes the full persona rewrite, so the old source-vs-rewrite guard no
    longer has two prose texts to compare. This guard instead checks that high-
    signal date/time/count values mentioned in the final response were present
    in the raw tool output events observed during the turn.
    """
    source_text = _tool_output_text(tool_events)
    if not source_text.strip():
        return MechanicalGuardResult(passed=True, violations=())

    source_facts = _tool_response_fact_set(source_text)
    response_facts = _tool_response_fact_set(response_text)
    if not response_facts:
        return MechanicalGuardResult(passed=True, violations=())

    unknown = sorted(response_facts - source_facts)
    if not unknown:
        return MechanicalGuardResult(passed=True, violations=())
    return MechanicalGuardResult(
        passed=False,
        violations=tuple(f"tool-output fact not found: {fact}" for fact in unknown),
    )


async def compare_semantic_entities(
    *,
    client: AsyncOpenAI,
    model: str,
    source: str,
    rewritten: str,
) -> ResponseGuardResult:
    response = await client.responses.create(
        model=model,
        instructions=(
            "You are a narrow response-integrity checker. Compare only named entities "
            "(people, organizations, products, locations, event titles) and their direct "
            "relationships. Dates, times, numbers, counts, URLs, and success/failure states "
            "have already been checked mechanically; do not reassess them. Do not judge tone "
            "or style. Return JSON only: {\"passed\": boolean, \"violations\": [string]}."
        ),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            {"source": source, "rewritten": rewritten},
                            ensure_ascii=False,
                        ),
                    }
                ],
            }
        ],
    )
    try:
        parsed: dict[str, Any] = json.loads(response.output_text)
    except (json.JSONDecodeError, TypeError) as error:
        raise RuntimeError("Semantic response guard returned invalid JSON.") from error
    violations = tuple(
        str(item) for item in parsed.get("violations", []) if isinstance(item, str)
    )
    return ResponseGuardResult(
        passed=bool(parsed.get("passed")) and not violations,
        violations=violations,
    )
