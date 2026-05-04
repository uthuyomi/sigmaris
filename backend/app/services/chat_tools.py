from __future__ import annotations

# 役割: LLM から呼ばれる Google 連携とアプリ内操作ツールを実行する。

from datetime import datetime, timedelta
from typing import Any

from app.schemas.google_tools import GoogleCalendarCreateEvent, GoogleProviderTokens
from app.services.chat_tool_definitions import FUNCTION_TOOL_MAP, FUNCTION_TOOLS
from app.services.app_data import (
    create_event,
    create_events,
    get_event_by_id,
    get_profile_context,
    list_conflicting_events,
    list_events,
    replace_travel_plan,
    search_events,
    update_event_external_link,
)
from app.services.google_calendar import (
    create_google_calendar_events,
    delete_google_calendar_events,
    delete_google_calendar_events_in_range,
    list_google_calendar_events,
)
from app.services.google_maps import RouteLookupError, get_simple_route_plan
from app.services.google_sheets import read_google_sheet_preview


def headers_to_google_tokens(headers: dict[str, str]) -> GoogleProviderTokens:
    return GoogleProviderTokens.model_validate(
        {
            "accessToken": headers.get("x-google-access-token") or None,
            "refreshToken": headers.get("x-google-refresh-token") or None,
        }
    )


def _has_google_tokens(tokens: GoogleProviderTokens) -> bool:
    return bool(tokens.access_token or tokens.refresh_token)


def _is_google_invalid_grant(error: BaseException) -> bool:
    message = str(error)
    return "invalid_grant" in message or "Bad Request" in message


def google_auth_error_result(error: BaseException) -> dict[str, Any]:
    if _is_google_invalid_grant(error):
        return {
            "ok": False,
            "status": "GOOGLE_AUTH_EXPIRED",
            "reason": (
                "Google authorization has expired or was revoked. "
                "Please sign in with Google again from the login/settings flow."
            ),
        }
    return {
        "ok": False,
        "status": "GOOGLE_AUTH_ERROR",
        "reason": f"Google authorization failed: {error}",
    }


async def execute_tool(
    *,
    jwt: str,
    google_tokens: GoogleProviderTokens,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if name == "list_google_calendar_events":
        if not _has_google_tokens(google_tokens):
            return {"ok": False, "reason": "Google provider token is not available."}
        events = list_google_calendar_events(
            tokens=google_tokens,
            calendar_id=arguments.get("calendarId"),
            time_min=arguments.get("timeMin"),
            time_max=arguments.get("timeMax"),
            max_results=arguments.get("maxResults"),
            query=arguments.get("query"),
        )
        return {"ok": True, "events": events, "count": len(events)}

    if name == "create_google_calendar_events":
        if not _has_google_tokens(google_tokens):
            return {"ok": False, "reason": "Google provider token is not available."}
        events = [
            GoogleCalendarCreateEvent.model_validate(event)
            for event in arguments.get("events", [])
        ]
        created_app_events = await create_events(
            jwt,
            [
                {
                    "title": event.title,
                    "description": event.description,
                    "location_text": event.location,
                    "starts_at": event.start,
                    "ends_at": event.end,
                    "source_type": "chat",
                    "metadata": {"provider": "google", "syncStatus": "pending"},
                }
                for event in events
            ],
        )
        google_create_targets = [
            (index, event, app_event)
            for index, (event, app_event) in enumerate(zip(events, created_app_events))
            if not app_event.get("external_event_id")
        ]
        created = create_google_calendar_events(
            tokens=google_tokens,
            calendar_id=arguments.get("calendarId"),
            events=[event for _, event, _ in google_create_targets],
        )
        for index, (_, _, app_event) in enumerate(google_create_targets):
            google_event = created[index] if index < len(created) else {}
            await update_event_external_link(
                jwt,
                event_id=app_event["id"],
                external_event_id=google_event.get("id"),
                metadata={
                    "provider": "google",
                    "htmlLink": google_event.get("htmlLink"),
                    "syncStatus": "synced" if google_event.get("id") else "pending",
                },
            )
        return {
            "ok": True,
            "createdCount": len(created),
            "created": created,
            "appCreatedCount": len(created_app_events),
            "skippedExistingGoogleCount": len(events) - len(google_create_targets),
            "createdAppEvents": created_app_events,
        }

    if name == "create_app_events":
        created_app_events = await create_events(
            jwt,
            [
                {
                    "title": event["title"],
                    "description": event.get("description"),
                    "location_text": event.get("location"),
                    "starts_at": event["start"],
                    "ends_at": event["end"],
                    "source_type": event.get("sourceType") or "chat",
                    "metadata": {"createdBy": "chat"},
                }
                for event in arguments.get("events", [])
            ],
        )
        return {
            "ok": True,
            "createdCount": len(created_app_events),
            "createdAppEvents": created_app_events,
        }

    if name == "delete_google_calendar_events":
        if not _has_google_tokens(google_tokens):
            return {"ok": False, "reason": "Google provider token is not available."}
        deleted = delete_google_calendar_events(
            tokens=google_tokens,
            calendar_id=arguments.get("calendarId"),
            event_ids=arguments.get("eventIds", []),
        )
        return {"ok": True, "deletedCount": len(deleted), "deleted": deleted}

    if name == "delete_google_calendar_events_in_range":
        if not _has_google_tokens(google_tokens):
            return {"ok": False, "reason": "Google provider token is not available."}
        deleted = delete_google_calendar_events_in_range(
            tokens=google_tokens,
            calendar_id=arguments.get("calendarId"),
            time_min=arguments["timeMin"],
            time_max=arguments["timeMax"],
            query=arguments.get("query"),
            max_results=arguments.get("maxResults"),
        )
        return {"ok": True, **deleted}

    if name == "read_google_sheet":
        if not _has_google_tokens(google_tokens):
            return {"ok": False, "reason": "Google provider token is not available."}
        preview = read_google_sheet_preview(tokens=google_tokens, url=arguments["url"])
        return {
            "ok": True,
            "spreadsheetId": preview["spreadsheetId"],
            "sheetTitle": preview["sheetTitle"],
            "rows": preview["rows"],
            "rowCount": len(preview["rows"]),
        }

    if name == "search_app_events":
        events = await search_events(
            jwt,
            query=arguments["query"],
            from_iso=arguments.get("fromIso"),
            to_iso=arguments.get("toIso"),
            limit=arguments.get("limit") or 10,
        )
        return {"ok": True, "events": events, "count": len(events)}

    if name == "list_app_events":
        events = await list_events(
            jwt,
            from_iso=arguments["fromIso"],
            to_iso=arguments["toIso"],
            limit=arguments.get("limit") or 50,
        )
        return {"ok": True, "events": events, "count": len(events)}

    if name == "read_home_context":
        context = await get_profile_context(jwt)
        return {
            "ok": True,
            "homeAddress": context["homeAddress"],
            "preferredTravelMode": context["preferredTravelMode"],
            "arrivalLeadMinutes": context["arrivalLeadMinutes"],
            "savedLocations": context["savedLocations"],
        }

    if name == "plan_google_route":
        travel_mode = arguments["travelMode"]
        try:
            timing_iso = arguments.get("arrivalTimeIso") or arguments.get("departureTimeIso")
            plan = await get_simple_route_plan(
                origin=arguments["origin"],
                destination=arguments["destination"],
                arrival_time_iso=timing_iso,
                mode=travel_mode,
            )
            return {"ok": True, "plan": plan.model_dump(by_alias=True)}
        except RouteLookupError as error:
            return {
                "ok": False,
                "reason": str(error),
                "status": error.status,
                "resolution": error.resolution.model_dump(by_alias=True) if error.resolution else None,
            }

    if name == "save_travel_plan_for_event":
        event = await get_event_by_id(jwt, arguments["eventId"])
        if not event:
            return {"ok": False, "reason": "Target event was not found."}
        destination_address = (
            arguments.get("destinationAddress")
            or arguments.get("destination")
            or event.get("location_text")
        )
        destination_label = arguments.get("destinationLabel") or event["title"]
        if not destination_address:
            return {
                "ok": False,
                "reason": (
                    "Target event has no destination. Provide destinationAddress when saving "
                    "a travel plan for an event whose location is only a site name."
                ),
            }

        selected_plan = arguments.get("plan")
        if not isinstance(selected_plan, dict):
            context = await get_profile_context(jwt)
            arrival_lead_minutes = int(context.get("arrivalLeadMinutes") or 0)
            event_start = datetime.fromisoformat(event["starts_at"].replace("Z", "+00:00"))
            desired_arrival = event_start - timedelta(minutes=arrival_lead_minutes)
            try:
                recalculated_plan = await get_simple_route_plan(
                    origin=arguments["origin"],
                    destination=destination_address,
                    arrival_time_iso=desired_arrival.isoformat(),
                    mode=arguments["travelMode"],
                )
            except RouteLookupError as error:
                return {
                    "ok": False,
                    "reason": str(error),
                    "status": error.status,
                    "resolution": error.resolution.model_dump(by_alias=True) if error.resolution else None,
                }
            selected_plan = recalculated_plan.model_dump(by_alias=True)

        recommended_departure_iso = selected_plan.get("recommendedDepartureIso")
        if not recommended_departure_iso:
            return {"ok": False, "reason": "The selected plan does not include a departure time."}
        travel_block_end_iso = selected_plan.get("estimatedArrivalIso") or event["starts_at"]

        warnings = await list_conflicting_events(
            jwt,
            starts_at=recommended_departure_iso,
            ends_at=travel_block_end_iso,
            exclude_event_ids=[event["id"]],
        )
        if warnings and not arguments.get("force"):
            return {
                "ok": False,
                "reason": "Conflicts detected before saving the travel block.",
                "warnings": warnings,
            }

        external_event_id = None
        if arguments.get("syncToGoogle") and _has_google_tokens(google_tokens):
            created = create_google_calendar_events(
                tokens=google_tokens,
                calendar_id=arguments.get("calendarId"),
                events=[
                    GoogleCalendarCreateEvent(
                        title=arguments.get("travelEventTitle") or f"Travel: {arguments['originLabel']} -> {event['title']}",
                        start=recommended_departure_iso,
                        end=travel_block_end_iso,
                        description=arguments.get("travelEventDescription"),
                        location=destination_address,
                    )
                ],
            )
            external_event_id = created[0]["id"] if created else None

        created_event = await create_event(
            jwt,
            title=arguments.get("travelEventTitle") or f"Travel: {arguments['originLabel']} -> {destination_label}",
            description=arguments.get("travelEventDescription"),
            location_text=destination_address,
            starts_at=recommended_departure_iso,
            ends_at=travel_block_end_iso,
            source_type="manual",
            external_event_id=external_event_id,
            metadata={
                "kind": "travel_block",
                "linkedEventId": event["id"],
                "originType": arguments.get("originType"),
                "originLabel": arguments["originLabel"],
                "destinationLabel": destination_label,
                "destinationAddress": destination_address,
                "travelMode": arguments["travelMode"],
            },
        )

        await replace_travel_plan(
            jwt,
            event_id=event["id"],
            origin_label=arguments["originLabel"],
            origin_address=arguments["origin"],
            destination_label=destination_label,
            destination_address=destination_address,
            travel_mode=arguments["travelMode"],
            recommended_departure_at=recommended_departure_iso,
            estimated_arrival_at=travel_block_end_iso,
            duration_minutes=int((selected_plan.get("durationSeconds") or 0) / 60) or None,
            route_summary=selected_plan.get("routeSummary"),
            route_steps=selected_plan.get("steps") or [],
            fare_text=selected_plan.get("fareText"),
            fare_amount=selected_plan.get("fareAmount"),
            fare_currency=selected_plan.get("fareCurrency"),
            transfer_count=selected_plan.get("transferCount"),
            walking_distance_meters=selected_plan.get("walkingDistanceMeters"),
            walking_duration_minutes=int((selected_plan.get("walkingDurationSeconds") or 0) / 60) or None,
            selected_candidate=None,
        )

        return {
            "ok": True,
            "createdEvent": created_event,
            "savedToGoogle": bool(external_event_id),
            "warnings": warnings,
        }
    return {"ok": False, "reason": f"Unknown tool: {name}"}


_headers_to_google_tokens = headers_to_google_tokens
_google_auth_error_result = google_auth_error_result
