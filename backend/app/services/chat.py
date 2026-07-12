from __future__ import annotations

# 役割: チャット応答生成、ツール実行、ストリーミングを制御する。

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
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

logger = logging.getLogger(__name__)
TOOL_EXECUTION_TIMEOUT_SECONDS = 45
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
    snapshot from whenever generation started — and persists exactly
    [existing thread history, this turn's new user message, this turn's
    new assistant reply]. `fallback_messages` (the old, unscoped
    behavior) is kept only for a caller that doesn't pass
    new_user_message, so nothing breaks silently if one exists.

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
            return [*existing, new_user_message, assistant_message]
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
