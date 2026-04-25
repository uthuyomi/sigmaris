# 役割: Google 連携 API の Pydantic スキーマを定義する。

from typing import Any

from pydantic import BaseModel, Field


class GoogleProviderTokens(BaseModel):
    access_token: str | None = Field(default=None, alias="accessToken", max_length=4096)
    refresh_token: str | None = Field(default=None, alias="refreshToken", max_length=4096)


class GoogleCalendarListRequest(BaseModel):
    tokens: GoogleProviderTokens
    calendar_id: str | None = Field(default=None, alias="calendarId", max_length=200)
    time_min: str | None = Field(default=None, alias="timeMin", max_length=64)
    time_max: str | None = Field(default=None, alias="timeMax", max_length=64)
    max_results: int | None = Field(default=None, alias="maxResults", ge=1, le=250)
    query: str | None = Field(default=None, max_length=200)


class GoogleCalendarCreateEvent(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    start: str = Field(max_length=64)
    end: str = Field(max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=500)


class GoogleCalendarCreateRequest(BaseModel):
    tokens: GoogleProviderTokens
    calendar_id: str | None = Field(default=None, alias="calendarId", max_length=200)
    events: list[GoogleCalendarCreateEvent] = Field(max_length=50)


class GoogleCalendarDeleteRequest(BaseModel):
    tokens: GoogleProviderTokens
    calendar_id: str | None = Field(default=None, alias="calendarId", max_length=200)
    event_ids: list[str] = Field(alias="eventIds", max_length=50)


class GoogleCalendarDeleteRangeRequest(BaseModel):
    tokens: GoogleProviderTokens
    calendar_id: str | None = Field(default=None, alias="calendarId", max_length=200)
    time_min: str = Field(alias="timeMin", max_length=64)
    time_max: str = Field(alias="timeMax", max_length=64)
    query: str | None = Field(default=None, max_length=200)
    max_results: int | None = Field(default=None, alias="maxResults", ge=1, le=250)


class GoogleSheetsPreviewRequest(BaseModel):
    tokens: GoogleProviderTokens
    url: str = Field(min_length=1, max_length=1000)


class GoogleApiErrorResponse(BaseModel):
    error: str
    detail: dict[str, Any] | None = None
