from __future__ import annotations

# 役割: チャットで利用できる関数ツール定義をまとめる。

from typing import Any


FUNCTION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "list_google_calendar_events",
        "description": "Read Google Calendar events within a date range.",
        "parameters": {
            "type": "object",
            "properties": {
                "calendarId": {"type": "string"},
                "timeMin": {"type": "string"},
                "timeMax": {"type": "string"},
                "maxResults": {"type": "integer", "minimum": 1, "maximum": 250},
                "query": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "create_google_calendar_events",
        "description": "Create events in Google Calendar after confirmation and mirror them into the app calendar database. For a timed event set start and end (ISO datetime). For an all-day event set allDay=true and date (YYYY-MM-DD) instead of start/end.",
        "parameters": {
            "type": "object",
            "properties": {
                "calendarId": {"type": "string"},
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "start": {"type": "string"},
                            "end": {"type": "string"},
                            "allDay": {"type": "boolean"},
                            "date": {"type": "string", "description": "YYYY-MM-DD for all-day events"},
                            "description": {"type": "string"},
                            "location": {"type": "string"},
                        },
                        "required": ["title"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["events"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "update_google_calendar_events",
        "description": "Edit an existing Google Calendar event after explicit confirmation. Provide eventId and only the fields to change (summary, start, end, location, description). Use this for requests like changing an event's time, place, or title.",
        "parameters": {
            "type": "object",
            "properties": {
                "calendarId": {"type": "string"},
                "eventId": {"type": "string"},
                "summary": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "location": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["eventId"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "create_app_events",
        "description": "Create events in the app calendar database after confirmation. By default, also sync them to Google Calendar when Google authorization is available; set skipGoogleSync only when the user explicitly requests app-calendar-only storage.",
        "parameters": {
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "start": {"type": "string"},
                            "end": {"type": "string"},
                            "description": {"type": "string"},
                            "location": {"type": "string"},
                            "sourceType": {
                                "type": "string",
                                "enum": ["manual", "chat", "sheet", "image"],
                            },
                        },
                        "required": ["title", "start", "end"],
                        "additionalProperties": False,
                    },
                },
                "skipGoogleSync": {"type": "boolean"},
            },
            "required": ["events"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "delete_google_calendar_events",
        "description": "Delete specific Google Calendar events after explicit confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "calendarId": {"type": "string"},
                "eventIds": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
            "required": ["eventIds"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "delete_google_calendar_events_in_range",
        "description": "Delete Google Calendar events in a date range after explicit confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "calendarId": {"type": "string"},
                "timeMin": {"type": "string"},
                "timeMax": {"type": "string"},
                "query": {"type": "string"},
                "maxResults": {"type": "integer", "minimum": 1, "maximum": 250},
            },
            "required": ["timeMin", "timeMax"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "read_google_sheet",
        "description": "Read a Google Sheets URL and preview rows.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "search_app_events",
        "description": "Search the app's existing events by title, location, or description.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "fromIso": {"type": "string"},
                "toIso": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "list_app_events",
        "description": "List app events in a date/time range without requiring a keyword. Use this for today, tomorrow, or day-after-tomorrow lookups before asking the user for a start time.",
        "parameters": {
            "type": "object",
            "properties": {
                "fromIso": {"type": "string"},
                "toIso": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["fromIso", "toIso"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "read_home_context",
        "description": "Read saved home address, preferred travel mode, and saved locations.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "plan_google_route",
        "description": "Look up a route with Google Maps for bicycle, car, or walking. Public transit is unavailable.",
        "parameters": {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "travelMode": {"type": "string", "enum": ["bicycle", "car", "walk"]},
                "arrivalTimeIso": {"type": "string"},
                "departureTimeIso": {"type": "string"},
            },
            "required": ["origin", "destination", "travelMode"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "save_travel_plan_for_event",
        "description": "Save a selected route into the app schedule as a travel block with a Google Maps navigation URL. Travel blocks are used by the app's travel reminder push notifications; when Travel alerts are enabled on the user's phone and the cron reminder job is running, the user can receive a smartphone notification when the departure time arrives and tap it to open Google Maps. By default, also sync the travel block to Google Calendar after confirmation when Google authorization is available. If plan is omitted, recalculate the route from the event start time and the user's arrival lead setting. If the event location is ambiguous, pass destinationAddress.",
        "parameters": {
            "type": "object",
            "properties": {
                "eventId": {"type": "string"},
                "originType": {"type": "string", "enum": ["home", "current", "saved", "custom"]},
                "origin": {"type": "string"},
                "originLabel": {"type": "string"},
                "destinationAddress": {"type": "string"},
                "destination": {"type": "string"},
                "destinationLabel": {"type": "string"},
                "travelMode": {"type": "string", "enum": ["bicycle", "car", "walk"]},
                "plan": {"type": "object"},
                "travelEventTitle": {"type": "string"},
                "travelEventDescription": {"type": "string"},
                "syncToGoogle": {"type": "boolean"},
                "calendarId": {"type": "string"},
                "force": {"type": "boolean"},
            },
            "required": ["eventId", "origin", "originLabel", "travelMode"],
            "additionalProperties": False,
        },
    },
]

FUNCTION_TOOL_MAP = {tool["name"]: tool for tool in FUNCTION_TOOLS}

