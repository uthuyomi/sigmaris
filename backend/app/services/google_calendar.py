from __future__ import annotations

# 役割: Google Calendar の読み書きを扱う。

from app.config import settings
from app.schemas.google_tools import (
    GoogleCalendarCreateEvent,
    GoogleProviderTokens,
)
from app.services.google_api import create_calendar_client


def list_google_calendar_events(
    *,
    tokens: GoogleProviderTokens,
    calendar_id: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int | None = None,
    query: str | None = None,
):
    calendar = create_calendar_client(tokens)
    resolved_calendar_id = calendar_id or settings.google_calendar_id or "primary"
    result = (
        calendar.events()
        .list(
            calendarId=resolved_calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results or 10,
            q=query,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return [
        {
            "id": event.get("id"),
            "summary": event.get("summary"),
            "description": event.get("description"),
            "location": event.get("location"),
            "htmlLink": event.get("htmlLink"),
            "status": event.get("status"),
            "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date"),
            "end": event.get("end", {}).get("dateTime") or event.get("end", {}).get("date"),
        }
        for event in result.get("items", [])
    ]


def create_google_calendar_events(
    *,
    tokens: GoogleProviderTokens,
    events: list[GoogleCalendarCreateEvent],
    calendar_id: str | None = None,
):
    if not events:
        return []

    calendar = create_calendar_client(tokens)
    resolved_calendar_id = calendar_id or settings.google_calendar_id or "primary"
    created = []

    for event in events:
        result = (
            calendar.events()
            .insert(
                calendarId=resolved_calendar_id,
                body={
                    "summary": event.title,
                    "description": event.description,
                    "location": event.location,
                    "start": {
                        "dateTime": event.start,
                        "timeZone": "Asia/Tokyo",
                    },
                    "end": {
                        "dateTime": event.end,
                        "timeZone": "Asia/Tokyo",
                    },
                },
            )
            .execute()
        )
        created.append(
            {
                "id": result.get("id"),
                "htmlLink": result.get("htmlLink"),
                "summary": result.get("summary"),
                "start": result.get("start", {}).get("dateTime"),
                "end": result.get("end", {}).get("dateTime"),
            }
        )

    return created


def delete_google_calendar_events(
    *,
    tokens: GoogleProviderTokens,
    event_ids: list[str],
    calendar_id: str | None = None,
):
    if not event_ids:
        return []

    calendar = create_calendar_client(tokens)
    resolved_calendar_id = calendar_id or settings.google_calendar_id or "primary"
    deleted = []

    for event_id in event_ids:
        calendar.events().delete(calendarId=resolved_calendar_id, eventId=event_id).execute()
        deleted.append({"id": event_id})

    return deleted


def delete_google_calendar_events_in_range(
    *,
    tokens: GoogleProviderTokens,
    time_min: str,
    time_max: str,
    query: str | None = None,
    max_results: int | None = None,
    calendar_id: str | None = None,
):
    events = list_google_calendar_events(
        tokens=tokens,
        calendar_id=calendar_id,
        time_min=time_min,
        time_max=time_max,
        query=query,
        max_results=max_results or 250,
    )
    deletable = [event for event in events if event.get("id") and event.get("status") != "cancelled"]
    deleted = delete_google_calendar_events(
        tokens=tokens,
        event_ids=[event["id"] for event in deletable if event.get("id")],
        calendar_id=calendar_id,
    )

    return {
        "matchedCount": len(events),
        "deletedCount": len(deleted),
        "deletedIds": [event["id"] for event in deleted],
        "deletedEvents": deletable,
    }
