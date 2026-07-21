from __future__ import annotations

# 役割: チャット応答生成、ツール実行、ストリーミングを制御する。

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from typing import Any
from google.auth.exceptions import RefreshError
from openai import AsyncOpenAI

from app.config import settings
from app.services.app_data import (
    ThreadVersionConflictError,
    get_chat_thread,
    get_chat_thread_version,
    get_profile_context,
    list_chat_messages,
    replace_chat_messages,
)
from app.services.chat_attachments import build_attachment_facts, extract_latest_image_contexts
from app.services.chat_prompts import build_ai_tone_instruction, build_system_prompt
from app.services.chat_messages import (
    _to_response_content,
    sanitize_messages_for_model,
    stream_ui_message_chunks,
)
from app.services.chat_tools import (
    FUNCTION_TOOL_MAP,
    execute_tool,
    google_auth_error_result,
    headers_to_google_tokens,
)
from app.services.chat_routing import (
    build_specialized_router_instruction,
    classify_chat_intent,
    tool_names_for_intent,
)
from app.services.citation_audit import persist_citation_audit, run_verification_checks, verify_response
from app.services.live_detail_masking import mask_tool_arguments
from app.services.live_event_details import persist_live_event_detail_bg_from_jwt
from app.services.live_events import emit_live_event
from app.services.evidence_search import build_evidence_context, gather_search_evidence

logger = logging.getLogger(__name__)
TOOL_EXECUTION_TIMEOUT_SECONDS = 45


def _model_tier(model: str) -> str:
    """Sigmaris Live の Model 表示用に、モデル名を config の各ティアと突き合わせて
    「標準/軽量/高度」を返す(local_llm.py::_openai_model_for_task と同じ区分)。
    実データのみ・捏造なし——一致しない場合は "other" を返す。"""
    if model == settings.openai_advanced_model:
        return "advanced"
    if model == settings.openai_nano_model:
        return "nano"
    if model == settings.openai_model:
        return "standard"
    return "other"
CONFIRMATION_MARKER_RE = re.compile(
    r"<!--\s*shiftpilot-confirmation\s+([\s\S]*?)\s*-->",
    re.DOTALL,
)
CONFIRMATION_REQUIRED_TOOLS = {
    "create_google_calendar_events",
    "create_app_events",
    "delete_google_calendar_events",
    "delete_google_calendar_events_in_range",
    "save_travel_plan_for_event",
}


def _extract_message_text(message: dict[str, Any]) -> str:
    return "\n".join(
        str(part.get("text", "")).strip()
        for part in message.get("parts", [])
        if part.get("type") == "text" and str(part.get("text", "")).strip()
    ).strip()


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return _extract_message_text(message)
    return ""


async def _gather_evidence_and_context(
    route: dict[str, Any], messages: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    """Phase G-2(docs/sigmaris/phase_g_report.md): if G-1's classify_
    chat_intent() flagged this turn as needing a web search, runs the
    search+structuring pipeline. Returns (evidence, evidence_context) --
    the raw structured evidence list is also returned (not just the
    formatted context string) because Phase G-3's Self-Critique step
    needs the same evidence to check the generated response against.

    A no-op (returns ([], None)) whenever needs_search is false — the
    common case — so no extra latency or LLM calls happen on ordinary
    turns (requirement 5, both G-2 and G-3)."""
    search_signal = route.get("search") or {}
    if not search_signal.get("needs_search"):
        return [], None

    user_question = _latest_user_text(messages)
    evidence = await gather_search_evidence(user_question=user_question, search_signal=search_signal)
    return evidence, build_evidence_context(evidence)


def _append_evidence_context(router_instruction: str, evidence_context: str | None) -> str:
    """Concatenates evidence_context onto router_instruction -- the same
    "concatenate a second context block onto an existing volatile string"
    pattern this codebase already uses elsewhere (e.g. Phase S-3's
    dissent_context appended onto preference_patterns_context in
    orchestrator/service.py) -- rather than adding a new parameter to
    build_system_prompt()/chat_prompts.py.

    Placement rationale (Phase A2 cache safety): router_instruction is
    already the second-least-stable block in build_system_prompt()'s
    ordering (chat_prompts.py's own comment: it's re-classified by an LLM
    call on every turn), so appending Evidence there — rather than
    anywhere in the fixed "rules"/"ai_tone"/"base_system" prefix — cannot
    invalidate more of OpenAI's prefix-based prompt cache than router_
    instruction's own per-turn volatility was already going to."""
    if not evidence_context:
        return router_instruction
    return f"{router_instruction}\n\n{evidence_context}" if router_instruction else evidence_context


async def _log_verification_advisory(
    final_text: str, evidence: list[dict[str, Any]], thread_id: str
) -> None:
    """Phase G-3/G-4: fire-and-forget wrapper for the streaming path's
    advisory-only verification. Runs both G-3's whole-response critique
    and G-4's claim-level citation-usage audit, logs anything flagged, and
    persists the audit rows for G-5's future aggregation (docs/sigmaris/
    phase_g_report.md) -- but never rewrites the already-streamed
    response text (see the module-level rationale above the streaming
    call site: BA4 8章's silent-buffering regression is the reason this
    stays advisory-only here, same as G-3).

    run_verification_checks() runs G-3 and G-4 concurrently and never
    rewrites, so no latency is wasted computing a rewrite this path would
    never use. critique_response()/audit_citation_usage() already never
    raise (they fail open internally), so this wrapper's own try/except is
    only a second safety net against something unexpected escaping it --
    an unawaited asyncio task that raises produces an unretrieved-
    exception warning but must never do anything worse."""
    try:
        critique, audit_results = await run_verification_checks(final_text, evidence)
        if critique["verdict"] != "no_contradiction":
            logger.warning(
                "self_critique: streaming response flagged verdict=%s thread_id=%s reason=%s",
                critique["verdict"],
                thread_id,
                critique.get("reason"),
            )
        if any(item.get("usage") == "distorted" for item in audit_results):
            logger.warning(
                "citation_audit: streaming response flagged distorted claim usage thread_id=%s",
                thread_id,
            )
        await persist_citation_audit(
            thread_id=thread_id, audit_results=audit_results, critique_verdict=critique.get("verdict")
        )
    except Exception:
        logger.exception("self_critique: advisory logging failed thread_id=%s", thread_id)


def _confirmation_choice(text: str) -> bool | None:
    normalized = text.strip().lower()
    if "shift_pilot_confirm:no" in normalized or "confirm_action:no" in normalized:
        return False
    if "shift_pilot_confirm:yes" in normalized or "confirm_action:yes" in normalized:
        return True
    return None


def _visible_message_text(message: dict[str, Any]) -> str:
    return CONFIRMATION_MARKER_RE.sub("", _extract_message_text(message)).strip()


def _recent_visible_context(messages: list[dict[str, Any]], *, limit: int = 12) -> str:
    lines = []
    for message in messages[-limit:]:
        text = _visible_message_text(message)
        if text:
            lines.append(f"{message.get('role', 'user')}: {text}")
    return "\n".join(lines)


def _conversation_requests_travel_reminder(messages: list[dict[str, Any]]) -> bool:
    context = _recent_visible_context(messages, limit=16).lower()
    keywords = (
        "移動通知",
        "移動予定通知",
        "スマホ通知",
        "マップ通知",
        "googleマップ",
        "google maps",
        "出発時間",
        "出発時刻",
        "間に合う移動",
        "travel reminder",
    )
    return any(keyword.lower() in context for keyword in keywords)


def _confirmed_tool_followup_input(
    *,
    tool_name: str,
    tool_result: dict[str, Any],
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    if tool_name not in {"create_google_calendar_events", "create_app_events"}:
        return None
    if not tool_result.get("ok") or tool_result.get("registrationStatus") != "registered":
        return None
    if not _conversation_requests_travel_reminder(messages):
        return None

    instruction = "\n".join(
        [
            "The user confirmed the calendar registration, and the registration tool completed successfully.",
            "The original user request also asked to create a travel reminder / smartphone Google Maps notification for the registered event.",
            "Continue from here. Use createdAppEvents[0].id from the tool result as the target eventId when possible.",
            "Use read_home_context if the origin is home or if a saved preferred travel mode/address is needed.",
            "Use plan_google_route if a route calculation is needed.",
            "Then call save_travel_plan_for_event. Do not claim the travel reminder was created until save_travel_plan_for_event returns ok=true.",
            "If required details are missing, ask only for those missing details.",
            "",
            "Recent conversation:",
            _recent_visible_context(messages),
            "",
            f"Confirmed tool: {tool_name}",
            f"Confirmed tool result JSON: {json.dumps(tool_result, ensure_ascii=False)}",
        ]
    )
    return [{"role": "user", "content": [{"type": "input_text", "text": instruction}]}]


def _auto_confirm_tools_for_confirmation(payload: dict[str, Any] | None) -> set[str]:
    if (
        payload
        and payload.get("tool") in {"create_google_calendar_events", "create_app_events"}
        and payload.get("autoContinueTravelReminder") is True
    ):
        return {"save_travel_plan_for_event"}
    return set()


def _looks_like_confirmation_update(text: str) -> bool:
    normalized = text.strip().lower()
    update_keywords = (
        "変更",
        "修正",
        "変えて",
        "直して",
        "登録",
        "入れて",
        "作成",
        "追加",
        "削除",
        "時間",
        "時刻",
        "日付",
        "場所",
        "タイトル",
        "メモ",
        "calendar",
        "register",
        "save",
        "create",
        "delete",
        "change",
        "update",
    )
    return any(keyword in normalized or keyword in text for keyword in update_keywords)


def _find_latest_pending_confirmation(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        text = _extract_message_text(message)
        matches = list(CONFIRMATION_MARKER_RE.finditer(text))
        if not matches:
            continue
        for match in reversed(matches):
            try:
                payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if (
                isinstance(payload, dict)
                and payload.get("tool") in CONFIRMATION_REQUIRED_TOOLS
                and isinstance(payload.get("arguments"), dict)
            ):
                return payload
    return None


def _confirmation_copy(tool_name: str, arguments: dict[str, Any]) -> tuple[str, str]:
    if tool_name == "save_travel_plan_for_event":
        title = "移動予定通知を入れますか？"
        description = "移動ブロックを予定に追加して、出発時間になったらスマホ通知からGoogleマップを開けるようにします。"
    elif tool_name in {"create_google_calendar_events", "create_app_events"}:
        events = arguments.get("events")
        count = len(events) if isinstance(events, list) else 1
        title = "予定を登録しますか？" if count <= 1 else f"{count}件の予定を登録しますか？"
        description = "内容を確認して、問題なければカレンダーへ登録します。"
    elif tool_name == "delete_google_calendar_events_in_range":
        title = "予定をまとめて削除しますか？"
        description = "指定した期間の予定を削除します。取り消しにくい操作なので確認してから実行します。"
    else:
        title = "予定を削除しますか？"
        description = "指定した予定を削除します。取り消しにくい操作なので確認してから実行します。"
    return title, description


def _build_confirmation_message(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    auto_continue_travel_reminder: bool = False,
) -> str:
    title, description = _confirmation_copy(tool_name, arguments)
    marker = {
        "tool": tool_name,
        "arguments": arguments,
        "title": title,
        "description": description,
    }
    if auto_continue_travel_reminder:
        title = "予定と移動通知を登録しますか？"
        marker["autoContinueTravelReminder"] = True
        description = (
            f"{description}\n\n"
            "予定登録が成功したら、そのまま移動時間を計算してスマホ通知用の移動予定も作ります。"
        )
        marker["title"] = title
        marker["description"] = description
    return (
        f"{title}\n\n"
        f"{description}\n\n"
        "下のボタンで実行するか選んでね。\n"
        f"<!-- shiftpilot-confirmation {json.dumps(marker, ensure_ascii=False)} -->"
    )


def _summarize_tool_result(tool_name: str, result: dict[str, Any]) -> str:
    if not result.get("ok"):
        reason = result.get("userFacingResult") or result.get("reason") or "原因不明のエラーです。"
        return f"実行できなかったよ。\n\n理由: {reason}"

    user_facing = result.get("userFacingResult")
    if tool_name == "save_travel_plan_for_event":
        maps_url = result.get("mapsNavigationUrl")
        extra = f"\n\nGoogleマップ: {maps_url}" if maps_url else ""
        return f"移動予定通知を登録したよ。出発時間になったらスマホ通知から開ける形だね。{extra}"
    if tool_name in {"create_google_calendar_events", "create_app_events"}:
        created_count = result.get("createdCount") or result.get("appCreatedCount") or 0
        return f"{user_facing or '予定を登録したよ。'}\n\n登録件数: {created_count}"
    if tool_name in {"delete_google_calendar_events", "delete_google_calendar_events_in_range"}:
        deleted_count = result.get("deletedCount") or result.get("count") or 0
        return f"削除を実行したよ。\n\n削除件数: {deleted_count}"
    return user_facing or "実行したよ。"


def _build_tool_ui_part(
    *,
    tool_call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    if result.get("ok") is False:
        return {
            "type": "dynamic-tool",
            "toolName": tool_name,
            "toolCallId": tool_call_id,
            "state": "output-error",
            "input": arguments,
            "errorText": str(result.get("reason") or result.get("error") or "Tool execution failed."),
        }

    return {
        "type": "dynamic-tool",
        "toolName": tool_name,
        "toolCallId": tool_call_id,
        "state": "output-available",
        "input": arguments,
        "output": result,
    }


def _tool_ui_chunks(
    *,
    tool_call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    input_chunk = {
        "type": "tool-input-available",
        "toolCallId": tool_call_id,
        "toolName": tool_name,
        "input": arguments,
        "dynamic": True,
    }
    if result.get("ok") is False:
        output_chunk = {
            "type": "tool-output-error",
            "toolCallId": tool_call_id,
            "errorText": str(result.get("reason") or result.get("error") or "Tool execution failed."),
            "dynamic": True,
        }
    else:
        output_chunk = {
            "type": "tool-output-available",
            "toolCallId": tool_call_id,
            "output": result,
            "dynamic": True,
        }

    return input_chunk, output_chunk


async def _execute_chat_tool(
    *,
    jwt: str,
    google_tokens: dict[str, str],
    thread_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    audit_info: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    logger.info("chat stream tool execute thread_id=%s tool=%s", thread_id, tool_name)
    try:
        return await asyncio.wait_for(
            execute_tool(
                jwt=jwt,
                google_tokens=google_tokens,
                name=tool_name,
                arguments=arguments,
                audit_info=audit_info,
            ),
            timeout=TOOL_EXECUTION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.exception(
            "chat tool timeout thread_id=%s tool=%s timeout_seconds=%s",
            thread_id,
            tool_name,
            TOOL_EXECUTION_TIMEOUT_SECONDS,
        )
        return {
            "ok": False,
            "reason": f"Tool timed out after {TOOL_EXECUTION_TIMEOUT_SECONDS} seconds.",
        }
    except RefreshError as error:
        logger.warning(
            "chat stream tool google auth failed thread_id=%s tool=%s error=%s",
            thread_id,
            tool_name,
            error,
        )
        return google_auth_error_result(error)
    except Exception as error:  # noqa: BLE001
        logger.exception("chat stream tool failed thread_id=%s tool=%s", thread_id, tool_name)
        return {"ok": False, "reason": str(error)}


# Lazy singleton so we don't reconstruct an AsyncOpenAI client on every
# call — classify_chat_intent(), run_chat_completion(), and
# stream_chat_completion_ui() all run on the hot path of every chat turn,
# same reasoning memory_search.py's _openai_embed_client already uses (see
# that module's identical comment). A fresh client per call meant a fresh
# TCP/TLS connection to api.openai.com every turn instead of reusing a
# keep-alive connection — see docs/sigmaris/
# incident_response_latency_investigation.md 8.5(c)-2.
_openai_client: AsyncOpenAI | None = None


def _require_openai_client() -> AsyncOpenAI:
    global _openai_client
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set for backend.")
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _parse_message_timestamp(message: dict[str, Any]) -> datetime | None:
    """Best-effort parse of a message dict's created_at for the
    chronological merge below (docs/sigmaris/phase_ba4_report.md,
    "メッセージ表示順序の崩れ" fix). Rows from list_chat_messages() always
    have one (chat_messages.created_at is NOT NULL), so None only matters
    defensively here for a value this function doesn't recognize."""
    value = message.get("created_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _chronological_sort_key(message: dict[str, Any]) -> tuple[bool, datetime]:
    parsed = _parse_message_timestamp(message)
    return (parsed is None, parsed or datetime.min.replace(tzinfo=UTC))


def _merge_messages_chronologically(
    existing: list[dict[str, Any]],
    new_user_message: dict[str, Any],
    assistant_message: dict[str, Any],
) -> list[dict[str, Any]]:
    """Places this turn's [new_user_message, assistant_message] pair into
    correct chronological order relative to `existing`, instead of always
    appending them at the tail.

    docs/sigmaris/phase_ba4_report.md ("メッセージ表示順序の崩れ" fix):
    16.5節で予告した通り、フロントエンド切断からの独立実行(バックグラウンド
    生成、16章)により、同一スレッドへの複数ターンがほぼ同時に進行しうる
    ようになった。従来の実装は常に新しいペアを配列の末尾へ追記していたため、
    「後から送られたが先に生成が完了したターン」が、常に「先に送られたが
    生成が長引いたターン」より前に永続化される——結果としてchat_messages
    自体に、実際の送信順とは異なる並びが恒久的に記録されていた
    (message_orderは配列の並びをそのまま採番するだけなので、この並び順の
    誤りをそれ自体では検知・修正できない)。

    orchestrator/service.pyがnew_user_messageに付与するcreated_at
    (`turn_started_at`、そのターンの処理が始まった時点の壁時計時刻)を
    根拠に、新しいペアをexistingの中の正しい位置へ挿入する形にした。
    assistant_messageには通常created_atが付かない(chat.py内で新規生成
    される)ため、new_user_messageと同じcreated_atを共有させる——同じ
    ターンのペアは常に隣接して並ぶべきで、かつ「実際に応答生成が完了した
    時刻」ではなく「そのターンが送信された時刻」で他ターンとの前後を
    比べるのが、ユーザーの体感する時系列と一致するため。
    """
    if not assistant_message.get("created_at"):
        turn_created_at = new_user_message.get("created_at")
        if turn_created_at:
            assistant_message = {**assistant_message, "created_at": turn_created_at}

    combined = [*existing, new_user_message, assistant_message]
    # sorted() is stable, so this turn's own pair (sharing one created_at)
    # keeps its [user, assistant] relative order, and any two existing rows
    # that happen to tie also keep their prior (message_order-derived)
    # relative order.
    combined.sort(key=_chronological_sort_key)
    return combined


async def _persist_chat_messages_safely(
    *,
    jwt: str,
    thread_id: str,
    fallback_messages: list[dict[str, Any]],
    new_user_message: dict[str, Any] | None,
    assistant_message: dict[str, Any],
    expected_version: int | None,
) -> None:
    """Persist a turn's messages without ever letting a failure here break
    the user-visible response — the assistant's reply has already been
    generated (and, for the streaming path, already sent to the client) by
    the time this runs, so failing loudly here would only hide a working
    answer behind a 500.

    Context-fabrication / message-order fix (docs/sigmaris/
    phase_ba4_report.md): `fallback_messages` used to be the *only* thing
    this persisted — the orchestrator's `messages` argument, which since
    Phase A1 is a cross-thread recent-log window (up to 40 messages
    spanning any of the caller's threads, built to give the LLM
    continuity), not this thread's own history. Every turn's
    replace_chat_messages() call was silently overwriting this thread's
    entire chat_messages with that cross-thread blend, which both (a)
    could bleed unrelated threads' content into this thread's saved
    history, feeding a future turn's "さっきの続きだけど" with content
    that never actually happened in *this* conversation, and (b) re-
    stamped every carried-over row with a fresh created_at (see
    _message_insert_payload()'s docstring), collapsing the whole thread's
    ordering to whatever instant each save happened to run at.

    When the caller supplies `new_user_message` (the orchestrator now
    does, on every call — see run_orchestrator_chat[_stream]()), this
    function instead re-reads *this thread's own* current messages via
    list_chat_messages() — fresh, right before writing, not a stale
    snapshot from whenever generation started — and merges this turn's new
    user/assistant pair into that history in chronological order
    (_merge_messages_chronologically(), keyed on new_user_message's
    created_at, not on when this write happens to run — see that
    function's docstring for why a blind tail-append reordered turns whose
    background generations finished out of send order). `fallback_messages`
    (the old, unscoped behavior) is kept only for a caller that doesn't
    pass new_user_message, so nothing breaks silently if one exists.

    A ThreadVersionConflictError means another writer replaced this
    thread's messages first (Phase A4). When new_user_message is
    available, this is now recoverable: the thread's current version and
    messages are re-fetched (picking up whatever the winning writer just
    saved) and the write is retried once, appending this turn on top of
    the now-current state rather than silently dropping it. Without
    new_user_message there isn't enough information to safely rebuild the
    array without risking duplicated window content, so that path keeps
    the original log-and-drop behavior — logged distinctly from other
    failures so it's identifiable in production logs.
    """

    async def _build_messages_to_store() -> list[dict[str, Any]]:
        if new_user_message is not None:
            existing = await list_chat_messages(jwt, thread_id=thread_id)
            return _merge_messages_chronologically(existing, new_user_message, assistant_message)
        return [*fallback_messages, assistant_message]

    messages_to_store = await _build_messages_to_store()
    try:
        await replace_chat_messages(
            jwt, thread_id=thread_id, messages=messages_to_store, expected_version=expected_version
        )
    except ThreadVersionConflictError:
        logger.warning(
            "chat: thread_id=%s concurrent write conflict (expected_version=%s)",
            thread_id,
            expected_version,
        )
        if new_user_message is None:
            logger.warning(
                "chat: thread_id=%s no new_user_message to safely retry with — "
                "this turn's messages were not persisted; existing DB state is untouched",
                thread_id,
            )
            return
        try:
            fresh_version = await get_chat_thread_version(jwt, thread_id)
            retry_messages = await _build_messages_to_store()
            await replace_chat_messages(
                jwt, thread_id=thread_id, messages=retry_messages, expected_version=fresh_version
            )
            logger.info(
                "chat: thread_id=%s persisted on retry after version conflict (retry_version=%s)",
                thread_id,
                fresh_version,
            )
        except ThreadVersionConflictError:
            logger.warning(
                "chat: thread_id=%s retry also hit a version conflict — "
                "this turn's messages were not persisted; existing DB state is untouched",
                thread_id,
            )
    except Exception:
        logger.exception("failed to persist chat messages thread_id=%s", thread_id)


async def chat_stream(
    messages: list[dict[str, str]],
    model: str,
    *,
    system: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncGenerator[str, None]:
    """Stream raw Chat Completions deltas for simple non-tool callers."""
    client = _require_openai_client()
    chat_messages: list[dict[str, str]] = []
    if system:
        chat_messages.append({"role": "system", "content": system})
    chat_messages.extend(messages)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": chat_messages,
        "stream": True,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def run_chat_completion(
    *,
    jwt: str,
    google_header_map: dict[str, str],
    thread_id: str,
    messages: list[dict[str, Any]],
    system: str | None = None,
    persist_messages: bool = True,
    audit_info: dict[str, str | None] | None = None,
    new_user_message: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]], str]:
    expected_version: int | None = None
    if persist_messages:
        thread = await get_chat_thread(jwt, thread_id)
        if not thread:
            raise RuntimeError("Requested chat thread was not found.")
        expected_version = await get_chat_thread_version(jwt, thread_id)

    profile_context = await get_profile_context(jwt)
    attachment_facts = build_attachment_facts(await extract_latest_image_contexts(messages))
    model_messages = sanitize_messages_for_model(messages)
    logger.info(
        "chat stream context ready thread_id=%s sanitized_messages=%s attachment_facts=%s",
        thread_id,
        len(model_messages),
        bool(attachment_facts),
    )

    client = _require_openai_client()
    route = await classify_chat_intent(
        messages=messages,
        attachment_facts=attachment_facts,
    )
    logger.info(
        "chat stream routed thread_id=%s intent=%s source=%s reason=%s",
        thread_id,
        route["intent"],
        route["source"],
        route["reason"],
    )
    router_instruction = build_specialized_router_instruction(
        intent=route["intent"],
        route_reason=route["reason"],
        route_source=route["source"],
    )
    evidence, evidence_context = await _gather_evidence_and_context(route, messages)
    router_instruction = _append_evidence_context(router_instruction, evidence_context)
    system_prompt = build_system_prompt(
        system,
        build_ai_tone_instruction(profile_context["aiTone"]),
        attachment_facts,
        router_instruction,
        agent_mode=not persist_messages,
    )
    google_tokens = headers_to_google_tokens(google_header_map)
    resolved_audit = audit_info or {"actor_type": "chat", "actor_ref": thread_id}
    final_text = ""
    confirmed_followup_input: list[dict[str, Any]] | None = None
    latest_user_text = _latest_user_text(messages)
    confirmation_choice = _confirmation_choice(latest_user_text)
    pending_confirmation = _find_latest_pending_confirmation(messages)
    auto_confirm_tools: set[str] = set()
    if confirmation_choice is False and pending_confirmation:
        final_text = "了解、今回は実行しないで止めておくよ。"
    elif confirmation_choice is True and pending_confirmation:
        auto_confirm_tools = _auto_confirm_tools_for_confirmation(pending_confirmation)
        tool_name = str(pending_confirmation["tool"])
        arguments = pending_confirmation["arguments"]
        tool_result = await _execute_chat_tool(
            jwt=jwt,
            google_tokens=google_tokens,
            thread_id=thread_id,
            tool_name=tool_name,
            arguments=arguments,
            audit_info=resolved_audit,
        )
        confirmed_followup_input = _confirmed_tool_followup_input(
            tool_name=tool_name,
            tool_result=tool_result,
            messages=messages,
        )
        if confirmed_followup_input:
            final_text = "予定は登録できたよ。続けて移動予定通知を準備するね。"
        else:
            final_text = _summarize_tool_result(tool_name, tool_result)

    if final_text.strip() and not confirmed_followup_input:
        assistant_message = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "parts": [{"type": "text", "text": final_text}],
            "metadata": {
                "routeIntent": route["intent"],
                "routeReason": route["reason"],
                "routeSource": route["source"],
            },
        }
        messages_to_store = [*messages, assistant_message]
        if persist_messages:
            await _persist_chat_messages_safely(
                jwt=jwt,
                thread_id=thread_id,
                fallback_messages=messages,
                new_user_message=new_user_message,
                assistant_message=assistant_message,
                expected_version=expected_version,
            )
        return final_text, messages_to_store, assistant_message["id"]

    block_confirmation_tools = (
        pending_confirmation is not None
        and confirmation_choice is None
        and not _looks_like_confirmation_update(latest_user_text)
    )
    enabled_tools = [
        FUNCTION_TOOL_MAP[name]
        for name in tool_names_for_intent(route["intent"])
        if name in FUNCTION_TOOL_MAP
        and not (block_confirmation_tools and name in CONFIRMATION_REQUIRED_TOOLS)
    ]
    response_input: list[dict[str, Any]] = confirmed_followup_input or [
        {
            "role": message["role"],
            "content": _to_response_content(message["role"], message["content"]),
        }
        for message in model_messages
    ]
    previous_response_id: str | None = None

    for _ in range(8):
        response = await client.responses.create(
            model=settings.openai_model,
            instructions=system_prompt,
            input=response_input,
            tools=enabled_tools,
            previous_response_id=previous_response_id,
        )

        function_calls = [
            item for item in response.output
            if getattr(item, "type", None) == "function_call"
        ]
        if function_calls:
            logger.info(
                "chat stream tool phase thread_id=%s tool_calls=%s",
                thread_id,
                [getattr(call, "name", "unknown") for call in function_calls],
            )
            outputs = []
            for function_call in function_calls:
                try:
                    arguments = json.loads(function_call.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                if function_call.name in CONFIRMATION_REQUIRED_TOOLS and function_call.name not in auto_confirm_tools:
                    auto_continue_travel_reminder = (
                        function_call.name in {"create_google_calendar_events", "create_app_events"}
                        and _conversation_requests_travel_reminder(messages)
                    )
                    final_text = _build_confirmation_message(
                        function_call.name,
                        arguments,
                        auto_continue_travel_reminder=auto_continue_travel_reminder,
                    )
                    break
                logger.info(
                    "chat stream tool execute thread_id=%s tool=%s",
                    thread_id,
                    function_call.name,
                )
                try:
                    tool_result = await asyncio.wait_for(
                        execute_tool(
                            jwt=jwt,
                            google_tokens=google_tokens,
                            name=function_call.name,
                            arguments=arguments,
                            audit_info=resolved_audit,
                        ),
                        timeout=TOOL_EXECUTION_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    logger.exception(
                        "chat tool timeout thread_id=%s tool=%s timeout_seconds=%s",
                        thread_id,
                        function_call.name,
                        TOOL_EXECUTION_TIMEOUT_SECONDS,
                    )
                    tool_result = {
                        "ok": False,
                        "reason": (
                            f"Tool timed out after {TOOL_EXECUTION_TIMEOUT_SECONDS} seconds. "
                            "Some events may already have been saved; rerun the same request to "
                            "continue, because existing app calendar events are skipped."
                        ),
                    }
                except RefreshError as error:
                    logger.warning(
                        "chat tool google auth failed thread_id=%s tool=%s error=%s",
                        thread_id,
                        function_call.name,
                        error,
                    )
                    tool_result = google_auth_error_result(error)
                except Exception as error:  # noqa: BLE001
                    logger.exception(
                        "chat tool failed thread_id=%s tool=%s",
                        thread_id,
                        function_call.name,
                    )
                    tool_result = {
                        "ok": False,
                        "reason": str(error),
                    }
                logger.info(
                    "chat stream tool complete thread_id=%s tool=%s ok=%s",
                    thread_id,
                    function_call.name,
                    tool_result.get("ok"),
                )
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": function_call.call_id,
                        "output": json.dumps(tool_result, ensure_ascii=False),
                    }
                )
            if final_text.strip():
                break
            previous_response_id = response.id
            response_input = outputs
            continue

        final_text = response.output_text or ""
        if final_text.strip():
            break

        previous_response_id = response.id
        response_input = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Continue."}],
            }
        ]

    if not final_text.strip():
        final_text = "今の条件では返答を確定しきれなかったよ。条件を少しだけ絞ってもう一回投げてみて。"

    if evidence:
        # Phase G-3/G-4(docs/sigmaris/phase_g_report.md): non-streaming
        # path gets the *full* effect (verification + conditional hedge
        # rewrite) -- everything here is synchronous and already awaited
        # before anything is returned to the caller, so there is no
        # streaming-silence risk to worry about (see self_critique.py's
        # module docstring for why the streaming path below is advisory-
        # only instead). verify_response() runs G-3's whole-response
        # verdict and G-4's claim-level usage audit concurrently, then
        # performs at most one rewrite call regardless of which layer
        # (or both) flagged something.
        final_text, critique, audit_results, _ = await verify_response(final_text, evidence)
        await persist_citation_audit(
            thread_id=thread_id, audit_results=audit_results, critique_verdict=critique.get("verdict")
        )

    assistant_message = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "parts": [{"type": "text", "text": final_text}],
        "metadata": {
            "routeIntent": route["intent"],
            "routeReason": route["reason"],
            "routeSource": route["source"],
        },
    }
    messages_to_store = [*messages, assistant_message]
    if persist_messages:
        await _persist_chat_messages_safely(
            jwt=jwt,
            thread_id=thread_id,
            fallback_messages=messages,
            new_user_message=new_user_message,
            assistant_message=assistant_message,
            expected_version=expected_version,
        )
    return final_text, messages_to_store, assistant_message["id"]


async def stream_chat_completion_ui(
    *,
    jwt: str,
    google_header_map: dict[str, str],
    thread_id: str,
    messages: list[dict[str, Any]],
    system: str | None = None,
    persist_messages: bool = True,
    audit_info: dict[str, str | None] | None = None,
    emit_status_delta: bool = True,
    new_user_message: dict[str, Any] | None = None,
) -> AsyncIterator[bytes]:
    message_id = str(uuid.uuid4())
    text_part_id = str(uuid.uuid4())
    logger.info("chat stream start thread_id=%s message_count=%s", thread_id, len(messages))
    yield f"data: {json.dumps({'type': 'start', 'messageId': message_id}, ensure_ascii=False)}\n\n".encode("utf-8")
    yield f"data: {json.dumps({'type': 'text-start', 'id': text_part_id}, ensure_ascii=False)}\n\n".encode("utf-8")
    if emit_status_delta:
        yield f"data: {json.dumps({'type': 'text-delta', 'id': text_part_id, 'delta': '確認中...\n'}, ensure_ascii=False)}\n\n".encode("utf-8")

    expected_version: int | None = None
    if persist_messages:
        thread = await get_chat_thread(jwt, thread_id)
        if not thread:
            raise RuntimeError("Requested chat thread was not found.")
        expected_version = await get_chat_thread_version(jwt, thread_id)

    profile_context = await get_profile_context(jwt)
    attachment_facts = build_attachment_facts(await extract_latest_image_contexts(messages))
    model_messages = sanitize_messages_for_model(messages)
    logger.info(
        "chat stream context ready thread_id=%s sanitized_messages=%s attachment_facts=%s",
        thread_id,
        len(model_messages),
        bool(attachment_facts),
    )

    client = _require_openai_client()
    # Sigmaris Live-2(docs/sigmaris/sigmaris_live_report.md): Live-1が最初の
    # 試験対象として提案したclassify_chat_intent()にのみ、イベント発行を
    # 追加した。emit_live_event()はfire-and-forget(呼び出し元をawaitで
    # 一切ブロックしない、失敗しても本来の意図分類処理には影響しない)。
    #
    # 本タスクでは、非streaming経路(run_chat_completion())には、あえて
    # 手を加えていない——Live-1が「リアルタイムな可視化」の対象として
    # 想定していたのはstreaming経路(このstream_chat_completion_ui())
    # であり、run_chat_completion()を使う呼び出し元(WearOS等、BA4報告書
    # 参照)には、そもそもSigmaris Liveを見ながら使うという利用形態が
    # 想定されない。依頼書「他の処理には手を加えないこと」を、対象範囲を
    # 広げない方向で厳格に解釈した(判断根拠、報告書に詳述)。
    #
    # invocation_idについて: orchestrator/service.pyが発行する真の
    # invocation_id(監査ログのID)は、現時点ではHTTP境界(schedule_agent_
    # client.py → routes/agent.py → ここ)を越えて渡されていない
    # (X-Correlation-IDヘッダは送信されているが、agent_chat_stream()は
    # まだこれを読んでいない)。共有ホットパスであるagent_chat_stream()の
    # シグネチャ変更は本タスクの範囲外と判断し、この関数内で既に生成済み
    # のmessage_id(979行目)を、イベント相関用のIDとして代用した。
    # 1ターン内でのイベント相関(started→finished)には十分だが、
    # orchestrator側の監査ログとの突き合わせはできない——次タスクへの
    # 申し送り事項として報告書に明記する。
    _live_event_started_at = time.perf_counter()
    emit_live_event("intent_classification_started", message_id)
    route = await classify_chat_intent(
        messages=messages,
        attachment_facts=attachment_facts,
    )
    emit_live_event(
        "intent_classification_finished",
        message_id,
        intent=route["intent"],
        source=route["source"],
        needs_search=bool((route.get("search") or {}).get("needs_search")),
        elapsed_ms=int((time.perf_counter() - _live_event_started_at) * 1000),
    )
    logger.info(
        "chat stream routed thread_id=%s intent=%s source=%s reason=%s",
        thread_id,
        route["intent"],
        route["source"],
        route["reason"],
    )
    router_instruction = build_specialized_router_instruction(
        intent=route["intent"],
        route_reason=route["reason"],
        route_source=route["source"],
    )
    evidence, evidence_context = await _gather_evidence_and_context(route, messages)
    router_instruction = _append_evidence_context(router_instruction, evidence_context)
    system_prompt = build_system_prompt(
        system,
        build_ai_tone_instruction(profile_context["aiTone"]),
        attachment_facts,
        router_instruction,
        agent_mode=not persist_messages,
    )
    google_tokens = headers_to_google_tokens(google_header_map)
    ui_audit_info: dict[str, str | None] = audit_info or {"actor_type": "chat", "actor_ref": thread_id}
    final_text = ""
    tool_parts: list[dict[str, Any]] = []
    confirmed_followup_input: list[dict[str, Any]] | None = None
    latest_user_text = _latest_user_text(messages)
    confirmation_choice = _confirmation_choice(latest_user_text)
    pending_confirmation = _find_latest_pending_confirmation(messages)
    auto_confirm_tools: set[str] = set()
    if confirmation_choice is False and pending_confirmation:
        final_text = "了解、今回は実行しないで止めておくよ。"
        payload = {"type": "text-delta", "id": text_part_id, "delta": final_text}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
    elif confirmation_choice is True and pending_confirmation:
        auto_confirm_tools = _auto_confirm_tools_for_confirmation(pending_confirmation)
        tool_name = str(pending_confirmation["tool"])
        arguments = pending_confirmation["arguments"]
        tool_call_id = f"confirmed-{uuid.uuid4()}"
        tool_result = await _execute_chat_tool(
            jwt=jwt,
            google_tokens=google_tokens,
            thread_id=thread_id,
            tool_name=tool_name,
            arguments=arguments,
            audit_info=ui_audit_info,
        )
        tool_parts.append(
            _build_tool_ui_part(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
                result=tool_result,
            )
        )
        for chunk in _tool_ui_chunks(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            result=tool_result,
        ):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
        confirmed_followup_input = _confirmed_tool_followup_input(
            tool_name=tool_name,
            tool_result=tool_result,
            messages=messages,
        )
        if confirmed_followup_input:
            final_text = "予定は登録できたよ。続けて移動予定通知を準備するね。\n\n"
        else:
            final_text = _summarize_tool_result(tool_name, tool_result)
        payload = {"type": "text-delta", "id": text_part_id, "delta": final_text}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    if final_text.strip() and not confirmed_followup_input:
        assistant_message = {
            "id": message_id,
            "role": "assistant",
            "parts": [*tool_parts, {"type": "text", "text": final_text}],
            "metadata": {
                "routeIntent": route["intent"],
                "routeReason": route["reason"],
                "routeSource": route["source"],
            },
        }
        messages_to_store = [*messages, assistant_message]
        if persist_messages:
            await _persist_chat_messages_safely(
                jwt=jwt,
                thread_id=thread_id,
                fallback_messages=messages,
                new_user_message=new_user_message,
                assistant_message=assistant_message,
                expected_version=expected_version,
            )
        for chunk in (
            {"type": "text-end", "id": text_part_id},
            {"type": "finish", "finishReason": "stop"},
        ):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
        return

    block_confirmation_tools = (
        pending_confirmation is not None
        and confirmation_choice is None
        and not _looks_like_confirmation_update(latest_user_text)
    )
    enabled_tools = [
        FUNCTION_TOOL_MAP[name]
        for name in tool_names_for_intent(route["intent"])
        if name in FUNCTION_TOOL_MAP
        and not (block_confirmation_tools and name in CONFIRMATION_REQUIRED_TOOLS)
    ]
    response_input: list[dict[str, Any]] = confirmed_followup_input or [
        {
            "role": message["role"],
            "content": _to_response_content(message["role"], message["content"]),
        }
        for message in model_messages
    ]
    previous_response_id: str | None = None
    final_text = ""

    # Sigmaris Live(docs/sigmaris/sigmaris_live_report.md、他の処理への
    # 拡大): 応答生成は、他の処理(記憶検索・意図分類)と異なり、既に
    # 本物のstreamingでユーザーへ届いている(Live-1、5.1節)。そのため
    # ここでは、既存のtext-delta streaming自体を可視化用に転用するのでは
    # なく(応答本文をSigmaris Liveの観測者向けイベントに含めないという
    # Live-1、4.2節のプライバシー方針は変更していない)、started/finished
    # の二値のみを、実際の生成開始・終了の実時間に忠実に送る——「実行中」
    # の表示期間が、本物の生成時間と正確に一致すること自体が、この処理
    # における「本物のリアルタイム性」の実装である(判断根拠、報告書に
    # 詳述)。
    _live_response_generation_started_at = time.perf_counter()
    emit_live_event("response_generation_started", message_id)

    for _ in range(8):
        logger.info(
            "chat stream model request thread_id=%s previous_response_id=%s input_items=%s tools=%s",
            thread_id,
            previous_response_id,
            len(response_input),
            [tool["name"] for tool in enabled_tools],
        )
        stream = await client.responses.create(
            model=settings.openai_model,
            instructions=system_prompt,
            input=response_input,
            tools=enabled_tools,
            previous_response_id=previous_response_id,
            stream=True,
        )

        function_calls: list[Any] = []
        completed_response_id: str | None = None
        had_text_delta = False

        async for event in stream:
            event_type = getattr(event, "type", None)

            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    had_text_delta = True
                    final_text += delta
                    payload = {
                        "type": "text-delta",
                        "id": text_part_id,
                        "delta": delta,
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
            elif event_type == "response.output_item.done":
                item = getattr(event, "item", None)
                if getattr(item, "type", None) == "function_call":
                    function_calls.append(item)
            elif event_type == "response.completed":
                response = getattr(event, "response", None)
                completed_response_id = getattr(response, "id", None)

        if function_calls:
            logger.info(
                "chat stream tool phase thread_id=%s tool_calls=%s",
                thread_id,
                [getattr(call, "name", "unknown") for call in function_calls],
            )
            outputs = []
            confirmation_requested = False
            for function_call in function_calls:
                try:
                    arguments = json.loads(function_call.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                if function_call.name in CONFIRMATION_REQUIRED_TOOLS and function_call.name not in auto_confirm_tools:
                    auto_continue_travel_reminder = (
                        function_call.name in {"create_google_calendar_events", "create_app_events"}
                        and _conversation_requests_travel_reminder(messages)
                    )
                    confirmation_text = _build_confirmation_message(
                        function_call.name,
                        arguments,
                        auto_continue_travel_reminder=auto_continue_travel_reminder,
                    )
                    if final_text.strip():
                        confirmation_text = f"\n\n{confirmation_text}"
                    final_text += confirmation_text
                    payload = {
                        "type": "text-delta",
                        "id": text_part_id,
                        "delta": confirmation_text,
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
                    confirmation_requested = True
                    break
                logger.info(
                    "chat stream tool execute thread_id=%s tool=%s",
                    thread_id,
                    function_call.name,
                )
                tool_call_id = str(getattr(function_call, "call_id", "") or uuid.uuid4())
                # Sigmaris Live: same fire-and-forget pattern as intent
                # classification/memory search/response generation above.
                # tool_name only (Live-1, 2.2節) — arguments can contain
                # location/calendar content and are never included.
                # tool_call_id is included so that Live-5's masked-detail
                # lookup can disambiguate multiple calls to the same tool
                # within one turn (message_id alone is shared by the whole
                # turn — see live_detail_masking.py's module docstring).
                _live_tool_call_started_at = time.perf_counter()
                emit_live_event(
                    "tool_call_started",
                    message_id,
                    tool_name=function_call.name,
                    tool_call_id=tool_call_id,
                )
                try:
                    tool_result = await asyncio.wait_for(
                        execute_tool(
                            jwt=jwt,
                            google_tokens=google_tokens,
                            name=function_call.name,
                            arguments=arguments,
                            audit_info=ui_audit_info,
                        ),
                        timeout=TOOL_EXECUTION_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    logger.exception(
                        "chat tool timeout thread_id=%s tool=%s timeout_seconds=%s",
                        thread_id,
                        function_call.name,
                        TOOL_EXECUTION_TIMEOUT_SECONDS,
                    )
                    tool_result = {
                        "ok": False,
                        "reason": f"Tool timed out after {TOOL_EXECUTION_TIMEOUT_SECONDS} seconds.",
                    }
                except RefreshError as error:
                    logger.warning(
                        "chat stream tool google auth failed thread_id=%s tool=%s error=%s",
                        thread_id,
                        function_call.name,
                        error,
                    )
                    tool_result = google_auth_error_result(error)
                except Exception as error:  # noqa: BLE001
                    logger.exception(
                        "chat stream tool failed thread_id=%s tool=%s",
                        thread_id,
                        function_call.name,
                    )
                    tool_result = {
                        "ok": False,
                        "reason": str(error),
                    }
                emit_live_event(
                    "tool_call_finished",
                    message_id,
                    tool_name=function_call.name,
                    tool_call_id=tool_call_id,
                    ok=bool(tool_result.get("ok")),
                    elapsed_ms=int((time.perf_counter() - _live_tool_call_started_at) * 1000),
                )
                # Sigmaris Live「詳細表示、+機密情報のマスキング」タスク:
                # 引数は、このアプリではほぼ全てがカレンダー・旅行計画等の
                # 自由記述であるため、mask_tool_arguments()(live_detail_
                # masking.py)が、文字列値を全てマスキングし、キー名
                # (=依頼書の「引数の種類」)と数値・真偽値のみ残す。
                # detail_keyはtool_call_id(1ターン中の複数回呼び出しを
                # 区別するため、message_id単体ではなくこちらを使う)。
                _masked_arguments, _tool_args_masked = mask_tool_arguments(arguments)
                persist_live_event_detail_bg_from_jwt(
                    jwt=jwt,
                    event_type="tool_call_finished",
                    detail_key=tool_call_id,
                    masked_detail={
                        "tool_name": function_call.name,
                        "arguments": _masked_arguments,
                        "any_masked": _tool_args_masked,
                    },
                )
                tool_parts.append(
                    _build_tool_ui_part(
                        tool_call_id=tool_call_id,
                        tool_name=function_call.name,
                        arguments=arguments,
                        result=tool_result,
                    )
                )
                for chunk in _tool_ui_chunks(
                    tool_call_id=tool_call_id,
                    tool_name=function_call.name,
                    arguments=arguments,
                    result=tool_result,
                ):
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
                logger.info(
                    "chat stream tool complete thread_id=%s tool=%s ok=%s",
                    thread_id,
                    function_call.name,
                    tool_result.get("ok"),
                )
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": function_call.call_id,
                        "output": json.dumps(tool_result, ensure_ascii=False),
                    }
                )
            if confirmation_requested:
                break
            previous_response_id = completed_response_id
            response_input = outputs
            continue

        if had_text_delta and final_text.strip():
            break

        previous_response_id = completed_response_id
        response_input = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Continue."}],
            }
        ]

    if not final_text.strip():
        final_text = "今の条件では返答を確定しきれなかったよ。条件を少しだけ絞ってもう一回投げてみて。"
        payload = {
            "type": "text-delta",
            "id": text_part_id,
            "delta": final_text,
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    emit_live_event(
        "response_generation_finished",
        message_id,
        response_length=len(final_text),
        elapsed_ms=int((time.perf_counter() - _live_response_generation_started_at) * 1000),
        # Model(Redesign-3): 応答生成で実際に使ったモデルと、そのティアを、
        # イベントにそのまま含める(捏造なし)。応答生成は settings.openai_model
        # を直接使う(1189行 client.responses.create(model=settings.openai_model))
        # ため、ここで確定している実値をそのまま載せるだけ——新しい判定ロジック・
        # 重い処理は追加していない。ティアは config の各モデル設定との一致で
        # 導出する(local_llm.py の _openai_model_for_task と同じ「標準/軽量/高度」
        # の区分)。
        model=settings.openai_model,
        model_tier=_model_tier(settings.openai_model),
    )

    if evidence:
        # Phase G-3/G-4: advisory-only in the streaming path -- deltas have
        # already been relayed to the client by this point, so rewriting
        # final_text here would not change what the user sees, and
        # awaiting the critique/audit synchronously would add silent dead
        # time right before the stream closes (the same failure mode BA4
        # 追補8/docs/sigmaris/phase_ba4_report.md 8章 already hit and fixed
        # once). Fired as an unawaited background task purely for
        # observability, mirroring response_guard.compare_response_to_
        # tool_outputs()'s existing "detect and log, never block" pattern.
        asyncio.create_task(_log_verification_advisory(final_text, evidence, thread_id))

    assistant_message = {
        "id": message_id,
        "role": "assistant",
        "parts": [*tool_parts, {"type": "text", "text": final_text}],
        "metadata": {
            "routeIntent": route["intent"],
            "routeReason": route["reason"],
            "routeSource": route["source"],
        },
    }
    messages_to_store = [*messages, assistant_message]
    if persist_messages:
        await _persist_chat_messages_safely(
            jwt=jwt,
            thread_id=thread_id,
            fallback_messages=messages,
            new_user_message=new_user_message,
            assistant_message=assistant_message,
            expected_version=expected_version,
        )

    for chunk in (
        {"type": "text-end", "id": text_part_id},
        {"type": "finish", "finishReason": "stop"},
    ):
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
