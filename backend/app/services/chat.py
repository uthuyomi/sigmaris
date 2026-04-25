from __future__ import annotations

# 役割: チャット応答生成、ツール実行、ストリーミングを制御する。

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any
from google.auth.exceptions import RefreshError
from openai import AsyncOpenAI

from app.config import settings
from app.services.app_data import get_chat_thread, get_profile_context, replace_chat_messages
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


def _require_openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set for backend.")
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def run_chat_completion(
    *,
    jwt: str,
    google_header_map: dict[str, str],
    thread_id: str,
    messages: list[dict[str, Any]],
    system: str | None = None,
) -> tuple[str, list[dict[str, Any]], str]:
    thread = await get_chat_thread(jwt, thread_id)
    if not thread:
        raise RuntimeError("Requested chat thread was not found.")

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
        client=client,
        model=settings.openai_model,
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
    )
    google_tokens = headers_to_google_tokens(google_header_map)
    enabled_tools = [
        FUNCTION_TOOL_MAP[name]
        for name in tool_names_for_intent(route["intent"])
        if name in FUNCTION_TOOL_MAP
    ]
    response_input: list[dict[str, Any]] = [
        {
            "role": message["role"],
            "content": _to_response_content(message["role"], message["content"]),
        }
        for message in model_messages
    ]
    previous_response_id: str | None = None
    final_text = ""

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
    await replace_chat_messages(jwt, thread_id=thread_id, messages=messages_to_store)
    return final_text, messages_to_store, assistant_message["id"]


async def stream_chat_completion_ui(
    *,
    jwt: str,
    google_header_map: dict[str, str],
    thread_id: str,
    messages: list[dict[str, Any]],
    system: str | None = None,
) -> AsyncIterator[bytes]:
    message_id = str(uuid.uuid4())
    text_part_id = str(uuid.uuid4())
    logger.info("chat stream start thread_id=%s message_count=%s", thread_id, len(messages))
    yield f"data: {json.dumps({'type': 'start', 'messageId': message_id}, ensure_ascii=False)}\n\n".encode("utf-8")
    yield f"data: {json.dumps({'type': 'text-start', 'id': text_part_id}, ensure_ascii=False)}\n\n".encode("utf-8")
    yield f"data: {json.dumps({'type': 'text-delta', 'id': text_part_id, 'delta': '確認中...\n'}, ensure_ascii=False)}\n\n".encode("utf-8")

    thread = await get_chat_thread(jwt, thread_id)
    if not thread:
        raise RuntimeError("Requested chat thread was not found.")

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
        client=client,
        model=settings.openai_model,
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
    )
    google_tokens = headers_to_google_tokens(google_header_map)
    enabled_tools = [
        FUNCTION_TOOL_MAP[name]
        for name in tool_names_for_intent(route["intent"])
        if name in FUNCTION_TOOL_MAP
    ]
    response_input: list[dict[str, Any]] = [
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
            for function_call in function_calls:
                try:
                    arguments = json.loads(function_call.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
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
        "parts": [{"type": "text", "text": final_text}],
        "metadata": {
            "routeIntent": route["intent"],
            "routeReason": route["reason"],
            "routeSource": route["source"],
        },
    }
    messages_to_store = [*messages, assistant_message]
    try:
        await replace_chat_messages(jwt, thread_id=thread_id, messages=messages_to_store)
    except Exception:
        logger.exception("failed to persist streamed chat messages")
    else:
        logger.info("chat stream persisted thread_id=%s message_id=%s", thread_id, message_id)

    for chunk in (
        {"type": "text-end", "id": text_part_id},
        {"type": "finish", "finishReason": "stop"},
    ):
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")


