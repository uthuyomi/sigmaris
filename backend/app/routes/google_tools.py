# 役割: Google 連携ツールを扱う FastAPI HTTP ルートを定義する。

from fastapi import APIRouter, Header, HTTPException

from app.schemas.google_tools import (
    GoogleCalendarCreateRequest,
    GoogleCalendarDeleteRangeRequest,
    GoogleCalendarDeleteRequest,
    GoogleCalendarListRequest,
    GoogleSheetsPreviewRequest,
)
from app.services.google_calendar import (
    create_google_calendar_events,
    delete_google_calendar_events,
    delete_google_calendar_events_in_range,
    list_google_calendar_events,
)
from app.services.google_sheets import read_google_sheet_preview
from app.services.supabase_rest import get_current_user

router = APIRouter(prefix="/api/google", tags=["google"])


def _require_jwt(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Missing bearer token."})
    return authorization.removeprefix("Bearer ").strip()


@router.post("/calendar/list")
async def google_calendar_list(
    input: GoogleCalendarListRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    await get_current_user(jwt)

    try:
        events = list_google_calendar_events(
            tokens=input.tokens,
            calendar_id=input.calendar_id,
            time_min=input.time_min,
            time_max=input.time_max,
            max_results=input.max_results,
            query=input.query,
        )
        return {"ok": True, "events": events, "count": len(events)}
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error


@router.post("/calendar/create")
async def google_calendar_create(
    input: GoogleCalendarCreateRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    await get_current_user(jwt)

    try:
        created = create_google_calendar_events(
            tokens=input.tokens,
            calendar_id=input.calendar_id,
            events=input.events,
        )
        return {"ok": True, "createdCount": len(created), "created": created}
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error


@router.post("/calendar/delete")
async def google_calendar_delete(
    input: GoogleCalendarDeleteRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    await get_current_user(jwt)

    try:
        deleted = delete_google_calendar_events(
            tokens=input.tokens,
            calendar_id=input.calendar_id,
            event_ids=input.event_ids,
        )
        return {"ok": True, "deletedCount": len(deleted), "deleted": deleted}
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error


@router.post("/calendar/delete-range")
async def google_calendar_delete_range(
    input: GoogleCalendarDeleteRangeRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    await get_current_user(jwt)

    try:
        result = delete_google_calendar_events_in_range(
            tokens=input.tokens,
            calendar_id=input.calendar_id,
            time_min=input.time_min,
            time_max=input.time_max,
            query=input.query,
            max_results=input.max_results,
        )
        return {"ok": True, **result}
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error


@router.post("/sheets/preview")
async def google_sheets_preview(
    input: GoogleSheetsPreviewRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    await get_current_user(jwt)

    try:
        preview = read_google_sheet_preview(tokens=input.tokens, url=input.url)
        return {"ok": True, **preview}
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
