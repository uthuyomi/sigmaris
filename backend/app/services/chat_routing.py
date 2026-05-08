from __future__ import annotations

# 役割: チャット意図分類と利用ツールの選択を行う。

import json
from typing import Any, Literal

from openai import AsyncOpenAI

ChatIntent = Literal[
    "general_chat",
    "event_lookup",
    "mobility_plan",
    "schedule_import",
    "calendar_write",
    "sync_control",
]


VALID_INTENTS: set[str] = {
    "general_chat",
    "event_lookup",
    "mobility_plan",
    "schedule_import",
    "calendar_write",
    "sync_control",
}

CALENDAR_WRITE_KEYWORDS = (
    "add to calendar",
    "add this to my calendar",
    "register in calendar",
    "save this schedule",
    "create event",
    "予定入れて",
    "予定を入れて",
    "予定入れ",
    "入れておいて",
    "入れといて",
    "入れて",
    "入れたい",
    "入れれ",
    "登録して",
    "追加して",
    "作って",
    "確定で",
    "確定",
    "カレンダーに",
    "書き直",
)

CALENDAR_WRITE_CONFIRMATION_KEYWORDS = (
    "お願い",
    "おねがい",
    "頼む",
    "たのむ",
    "よろしく",
    "ok",
    "okay",
    "yes",
    "はい",
    "うん",
    "それで",
    "その内容",
    "それ",
    "1で",
    "１で",
    "確定",
)

PENDING_CALENDAR_WRITE_CONTEXT_KEYWORDS = (
    "カレンダーに入れていい",
    "入れていい",
    "登録していい",
    "追加していい",
    "確定でいい",
    "予定",
    "タイトル",
    "日時",
    "場所",
    "calendar",
    "register",
    "add",
)


def latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        texts = [
            str(part.get("text", "")).strip()
            for part in message.get("parts", [])
            if part.get("type") == "text" and str(part.get("text", "")).strip()
        ]
        return "\n".join(texts).strip()
    return ""


def has_attachment(messages: list[dict[str, Any]]) -> bool:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        return any(part.get("type") == "file" for part in message.get("parts", []))
    return False


def heuristic_intent(
    *,
    latest_text: str,
    context_text: str = "",
    has_file_attachment: bool,
    has_image_context: bool,
) -> tuple[ChatIntent | None, str | None]:
    lowered = latest_text.lower()
    lowered_context = context_text.lower()

    if has_file_attachment or has_image_context:
        return "schedule_import", "attachment-present"

    if "spreadsheet" in lowered or "sheet" in lowered or "スプレッドシート" in latest_text or "勤務表" in latest_text:
        return "schedule_import", "sheet-keyword"

    if any(keyword in lowered or keyword in latest_text for keyword in CALENDAR_WRITE_KEYWORDS):
        return "calendar_write", "calendar-write-keyword"

    if (
        any(keyword in lowered or keyword in latest_text for keyword in CALENDAR_WRITE_CONFIRMATION_KEYWORDS)
        and any(
            keyword in lowered_context or keyword in context_text
            for keyword in PENDING_CALENDAR_WRITE_CONTEXT_KEYWORDS
        )
    ):
        return "calendar_write", "calendar-write-confirmation-context"

    if (
        "バス" in latest_text
        or "電車" in latest_text
        or "地下鉄" in latest_text
        or "徒歩" in latest_text
        or "自転車" in latest_text
        or "車" in latest_text
        or "移動" in latest_text
        or "何時に出" in latest_text
        or "どう行" in latest_text
        or "route" in lowered
    ):
        return "mobility_plan", "mobility-keyword"

    if (
        "google calendar" in lowered
        or "カレンダーに" in latest_text
        or "登録して" in latest_text
        or "追加して" in latest_text
        or "削除して" in latest_text
        or "消して" in latest_text
        or "入れ替えて" in latest_text
        or "同期" in latest_text
    ):
        return "calendar_write", "calendar-keyword"

    if "予定" in latest_text or "何日" in latest_text or "どの日" in latest_text or "いつ" in latest_text:
        return "event_lookup", "event-keyword"

    return None, None


async def classify_chat_intent(
    *,
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
    attachment_facts: str,
) -> dict[str, str]:
    latest_text = latest_user_text(messages)
    has_file_attachment = has_attachment(messages)
    has_image_context = bool(attachment_facts)
    context_text = "\n".join(
        " ".join(
            str(part.get("text", "")).strip()
            for part in message.get("parts", [])
            if part.get("type") == "text" and str(part.get("text", "")).strip()
        )
        for message in messages[-8:]
    )

    guessed_intent, guessed_reason = heuristic_intent(
        latest_text=latest_text,
        context_text=context_text,
        has_file_attachment=has_file_attachment,
        has_image_context=has_image_context,
    )
    if guessed_intent:
        return {
            "intent": guessed_intent,
            "reason": guessed_reason or "heuristic",
            "source": "heuristic",
        }

    transcript_lines: list[str] = []
    for message in messages[-6:]:
        role = str(message.get("role", "user"))
        texts = [
            str(part.get("text", "")).strip()
            for part in message.get("parts", [])
            if part.get("type") == "text" and str(part.get("text", "")).strip()
        ]
        if texts:
            transcript_lines.append(f"{role}: {' '.join(texts)}")
    transcript = "\n".join(transcript_lines)[:4000]

    prompt = "\n".join(
        [
            "Classify the user request for ShiftPilotAI.",
            'Return JSON only like {"intent":"...","reason":"..."}.',
            "Valid intents: general_chat, event_lookup, mobility_plan, schedule_import, calendar_write, sync_control.",
            "Use mobility_plan for route, departure, public-transit questions, walking, driving, bicycle, or home-to-destination guidance. Public-transit auto planning is unavailable; answer with that limitation and offer car, walking, or bicycle route planning.",
            "Use schedule_import for images, spreadsheets, work schedules, shift tables, or extracting events from files.",
            "Use calendar_write for adding, deleting, replacing, writing, or syncing calendar events.",
            "Use calendar_write for Japanese phrases such as 入れて, 入れておいて, 予定入れて, 登録して, 追加して, 確定で, or 作って when they refer to a schedule/event.",
            "Use calendar_write when the latest user message is a short confirmation such as お願い, OK, はい, それで, 1でお願い, or 確定 and the recent conversation proposed adding/registering an event.",
            "Use event_lookup for identifying which app event/day the user refers to.",
            "Use sync_control for integration or sync mode settings.",
            "Use general_chat only if no specialized intent is dominant.",
            f"has_attachment={has_file_attachment}",
            f"has_image_context={has_image_context}",
            transcript,
        ]
    )

    try:
        response = await client.responses.create(
            model=model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        )
        payload = json.loads(response.output_text or "{}")
        intent = payload.get("intent")
        if intent not in VALID_INTENTS:
            intent = "general_chat"
        return {
            "intent": intent,
            "reason": str(payload.get("reason") or "llm-router"),
            "source": "llm",
        }
    except Exception:
        return {
            "intent": "general_chat",
            "reason": "llm-router-fallback",
            "source": "fallback",
        }


def build_specialized_router_instruction(
    *,
    intent: ChatIntent,
    route_reason: str,
    route_source: str,
) -> str:
    common = [
        f"Routed intent: {intent}.",
        f"Routing source: {route_source}.",
        f"Routing reason: {route_reason}.",
    ]
    details: dict[ChatIntent, list[str]] = {
        "general_chat": [
            "Handle this as general planning chat.",
            "Use tools only when they materially improve the answer.",
            "If the user asks to add, register, confirm, save, or put an event into the calendar, use the available calendar write tools instead of saying write tools are unavailable.",
        ],
        "event_lookup": [
            "This request likely refers to an existing event.",
            "Calendar and app-event reads are non-destructive, so perform them without asking for confirmation.",
            "If the user asks to add, register, confirm, save, or put an event into the calendar after a lookup, use the calendar write tools instead of saying write tools are unavailable.",
            "If the user gives a relative date such as today, tomorrow, or the day after tomorrow, use list_app_events for that whole day before asking the user to restate dates or start times.",
            "Use search_app_events for keyword matching, but if search misses on a known day, inspect list_app_events results for that day.",
            "If app events return no plausible match, fall back to list_google_calendar_events before saying the event was not found.",
            "When falling back to Google Calendar, search the likely day or a narrow adjacent-day window and try practical query variants from the title, location, and address fragments.",
            "If Google Calendar returns GOOGLE_AUTH_EXPIRED, say reconnection is needed, but still use app events and known user-provided details before asking for the missing field.",
        ],
        "mobility_plan": [
            "This request is primarily about travel planning.",
            "Use read_home_context if the user says home or does not specify the travel mode.",
            "Calendar and app-event reads are non-destructive, so perform them without asking for confirmation.",
            "Use list_app_events when the date is known or relative, then inspect the day's events for the destination or site name.",
            "Use search_app_events when the destination or event name is referenced indirectly.",
            "If app event lookup returns no plausible match, fall back to list_google_calendar_events before asking the user to repeat the schedule details.",
            "Ask for the start time only after app events and available Google Calendar reads both fail to provide it.",
            "Public-transit auto planning is unavailable in this app. Do not attempt bus or train route lookup.",
            "Use plan_google_route only for car, walk, or bicycle if it helps provide a useful comparison without asking another question.",
            "When the user explicitly wants to add the route into the schedule, save it with save_travel_plan_for_event after confirmation.",
            "If the event location is only a site name but an exact destination address is known from the conversation, pass it as destinationAddress when saving.",
        ],
        "schedule_import": [
            "This request is primarily about importing schedules.",
            "Use attachment facts and read_google_sheet when relevant.",
        ],
        "calendar_write": [
            "This request is primarily about writing or replacing calendar events.",
            "For ordinary phrases like 'add to calendar', 'register in calendar', or 'save this schedule', use create_google_calendar_events so the event is saved to both Google Calendar and the app calendar database.",
            "Use create_app_events with skipGoogleSync=true only when the user explicitly says app-calendar-only, local-only, or not to write to Google Calendar.",
            "Confirm destructive actions before deletion or replacement.",
        ],
        "sync_control": [
            "This request is about sync or integration control.",
            "Answer operationally and clearly.",
        ],
    }
    return "\n".join([*common, *details[intent]])


def tool_names_for_intent(intent: ChatIntent) -> list[str]:
    if intent == "general_chat":
        return [
            "read_home_context",
            "search_app_events",
            "list_app_events",
            "create_google_calendar_events",
            "create_app_events",
        ]
    if intent == "event_lookup":
        return [
            "search_app_events",
            "list_app_events",
            "list_google_calendar_events",
            "create_google_calendar_events",
            "create_app_events",
            "read_home_context",
        ]
    if intent == "mobility_plan":
        return [
            "read_home_context",
            "search_app_events",
            "list_app_events",
            "list_google_calendar_events",
            "plan_google_route",
            "save_travel_plan_for_event",
        ]
    if intent == "schedule_import":
        return [
            "read_google_sheet",
            "create_google_calendar_events",
            "create_app_events",
            "search_app_events",
            "read_home_context",
        ]
    if intent == "calendar_write":
        return [
            "read_home_context",
            "search_app_events",
            "list_app_events",
            "list_google_calendar_events",
            "create_google_calendar_events",
            "create_app_events",
            "delete_google_calendar_events",
            "delete_google_calendar_events_in_range",
            "read_google_sheet",
            "plan_google_route",
            "save_travel_plan_for_event",
        ]
    return ["read_home_context", "search_app_events", "list_app_events", "list_google_calendar_events"]
