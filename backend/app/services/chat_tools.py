from __future__ import annotations

# 役割: LLM から呼ばれる Google 連携とアプリ内操作ツールを実行する。

from datetime import datetime, timedelta
from typing import Any

from app.schemas.google_tools import GoogleCalendarCreateEvent, GoogleProviderTokens
from app.services.audit_log import AuditContext
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
    update_google_calendar_events,
)
from app.services.google_maps import RouteLookupError, get_simple_route_plan
from app.services.google_maps_url import build_google_maps_directions_url
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


def _registration_success_message(
    *,
    app_count: int,
    google_count: int,
    google_skipped: bool = False,
) -> str:
    if google_count:
        return f"REGISTERED: saved {app_count} event(s) to the app calendar and {google_count} event(s) to Google Calendar."
    if google_skipped:
        return f"REGISTERED: saved {app_count} event(s) to the app calendar. Google Calendar sync was skipped."
    return f"REGISTERED: saved {app_count} event(s) to the app calendar."


def _build_audit(audit_info: dict[str, str | None] | None, action: str) -> AuditContext | None:
    if audit_info is None:
        return None
    return AuditContext(
        action=action,
        actor_type=audit_info.get("actor_type") or "api_direct",
        actor_ref=audit_info.get("actor_ref"),
        reason=audit_info.get("reason"),
    )


async def execute_tool(
    *,
    jwt: str,
    google_tokens: GoogleProviderTokens,
    name: str,
    arguments: dict[str, Any],
    audit_info: dict[str, str | None] | None = None,
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
            return {
                "ok": False,
                "registrationStatus": "not_registered",
                "reason": "Google provider token is not available.",
                "userFacingResult": (
                    "NOT_REGISTERED: Google authorization is unavailable, so the event was not saved. "
                    "Ask the user to reconnect Google or use app-calendar-only registration."
                ),
            }
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
            audit_ctx=_build_audit(audit_info, "created"),
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
                audit_ctx=_build_audit(audit_info, "synced"),
            )
        return {
            "ok": True,
            "registrationStatus": "registered",
            "userFacingResult": _registration_success_message(
                app_count=len(created_app_events),
                google_count=len(created),
            ),
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
            audit_ctx=_build_audit(audit_info, "created"),
        )
        should_sync_to_google = not arguments.get("skipGoogleSync") and _has_google_tokens(google_tokens)
        google_create_targets = [
            app_event
            for app_event in created_app_events
            if not app_event.get("external_event_id")
        ]
        created_google_events: list[dict[str, Any]] = []
        if should_sync_to_google and google_create_targets:
            created_google_events = create_google_calendar_events(
                tokens=google_tokens,
                events=[
                    GoogleCalendarCreateEvent(
                        title=event["title"],
                        start=event["starts_at"],
                        end=event["ends_at"],
                        description=event.get("description"),
                        location=event.get("location_text"),
                    )
                    for event in google_create_targets
                ],
            )
            for index, app_event in enumerate(google_create_targets):
                google_event = created_google_events[index] if index < len(created_google_events) else {}
                await update_event_external_link(
                    jwt,
                    event_id=app_event["id"],
                    external_event_id=google_event.get("id"),
                    metadata={
                        **(app_event.get("metadata") or {}),
                        "provider": "google",
                        "htmlLink": google_event.get("htmlLink"),
                        "syncStatus": "synced" if google_event.get("id") else "pending",
                    },
                    audit_ctx=_build_audit(audit_info, "synced"),
                )
        return {
            "ok": True,
            "registrationStatus": "registered",
            "userFacingResult": _registration_success_message(
                app_count=len(created_app_events),
                google_count=len(created_google_events),
                google_skipped=bool(arguments.get("skipGoogleSync")) or not _has_google_tokens(google_tokens),
            ),
            "createdCount": len(created_app_events),
            "createdAppEvents": created_app_events,
            "googleCreatedCount": len(created_google_events),
            "createdGoogleEvents": created_google_events,
            "googleSyncSkipped": bool(arguments.get("skipGoogleSync")) or not _has_google_tokens(google_tokens),
        }

    if name == "update_google_calendar_events":
        if not _has_google_tokens(google_tokens):
            return {"ok": False, "reason": "Google provider token is not available."}
        updated = update_google_calendar_events(
            tokens=google_tokens,
            calendar_id=arguments.get("calendarId"),
            event_id=arguments["eventId"],
            summary=arguments.get("summary"),
            start=arguments.get("start"),
            end=arguments.get("end"),
            location=arguments.get("location"),
            description=arguments.get("description"),
        )
        return {"ok": True, "updated": updated}

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
        maps_navigation_url = build_google_maps_directions_url(
            origin=arguments["origin"],
            destination=destination_address,
            travel_mode=arguments["travelMode"],
        )
        travel_event_description = arguments.get("travelEventDescription") or "\n".join(
            part
            for part in [
                str(selected_plan.get("durationText") or "").strip(),
                f"Google Maps: {maps_navigation_url}",
            ]
            if part
        )
        should_sync_to_google = arguments.get("syncToGoogle") is not False and _has_google_tokens(google_tokens)
        if should_sync_to_google:
            created = create_google_calendar_events(
                tokens=google_tokens,
                calendar_id=arguments.get("calendarId"),
                events=[
                    GoogleCalendarCreateEvent(
                        title=arguments.get("travelEventTitle") or f"Travel: {arguments['originLabel']} -> {event['title']}",
                        start=recommended_departure_iso,
                        end=travel_block_end_iso,
                        description=travel_event_description,
                        location=destination_address,
                    )
                ],
            )
            external_event_id = created[0]["id"] if created else None

        created_event = await create_event(
            jwt,
            title=arguments.get("travelEventTitle") or f"Travel: {arguments['originLabel']} -> {destination_label}",
            description=travel_event_description,
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
                "mapsNavigationUrl": maps_navigation_url,
            },
            audit_ctx=_build_audit(audit_info, "travel_plan_saved"),
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
            "registrationStatus": "registered",
            "userFacingResult": _registration_success_message(
                app_count=1,
                google_count=1 if external_event_id else 0,
                google_skipped=not should_sync_to_google,
            ),
            "createdEvent": created_event,
            "savedToGoogle": bool(external_event_id),
            "mapsNavigationUrl": maps_navigation_url,
            "warnings": warnings,
        }
    return {"ok": False, "reason": f"Unknown tool: {name}"}


_headers_to_google_tokens = headers_to_google_tokens
_google_auth_error_result = google_auth_error_result
