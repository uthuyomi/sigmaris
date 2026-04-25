# 役割: 移動計画 API の Pydantic スキーマを定義する。

from typing import Literal

from pydantic import BaseModel, Field


TravelMode = Literal["bicycle", "car", "walk"]
OriginType = Literal["home", "current", "saved", "custom"]
SurfaceTravelMode = Literal["bicycle", "car", "walk"]


class MobilityPlanRequest(BaseModel):
    origin_type: OriginType = Field(alias="originType")
    origin: str = Field(min_length=1, max_length=500)
    destination: str = Field(min_length=1, max_length=500)
    arrival_time_iso: str = Field(alias="arrivalTimeIso", max_length=64)
    travel_mode: TravelMode = Field(alias="travelMode")


class RoutePlanStep(BaseModel):
    instruction: str
    travel_mode: str = Field(alias="travelMode")
    line_name: str | None = Field(default=None, alias="lineName")
    departure_stop: str | None = Field(default=None, alias="departureStop")
    arrival_stop: str | None = Field(default=None, alias="arrivalStop")
    departure_time: str | None = Field(default=None, alias="departureTime")
    arrival_time: str | None = Field(default=None, alias="arrivalTime")
    distance_text: str | None = Field(default=None, alias="distanceText")
    duration_text: str | None = Field(default=None, alias="durationText")


class RoutePlan(BaseModel):
    mode: TravelMode
    origin_label: str = Field(alias="originLabel")
    destination_label: str = Field(alias="destinationLabel")
    recommended_departure_time: str | None = Field(default=None, alias="recommendedDepartureTime")
    recommended_departure_iso: str | None = Field(default=None, alias="recommendedDepartureIso")
    estimated_arrival_time: str | None = Field(default=None, alias="estimatedArrivalTime")
    estimated_arrival_iso: str | None = Field(default=None, alias="estimatedArrivalIso")
    duration_text: str | None = Field(default=None, alias="durationText")
    duration_seconds: int | None = Field(default=None, alias="durationSeconds")
    walking_duration_text: str | None = Field(default=None, alias="walkingDurationText")
    walking_duration_seconds: int | None = Field(default=None, alias="walkingDurationSeconds")
    walking_distance_text: str | None = Field(default=None, alias="walkingDistanceText")
    walking_distance_meters: int | None = Field(default=None, alias="walkingDistanceMeters")
    transfer_count: int | None = Field(default=None, alias="transferCount")
    fare_text: str | None = Field(default=None, alias="fareText")
    fare_amount: float | None = Field(default=None, alias="fareAmount")
    fare_currency: str | None = Field(default=None, alias="fareCurrency")
    route_summary: str | None = Field(default=None, alias="routeSummary")
    steps: list[RoutePlanStep]


class RouteLookupCandidate(BaseModel):
    formatted_address: str = Field(alias="formattedAddress")
    latitude: float
    longitude: float
    place_id: str | None = Field(default=None, alias="placeId")


class RouteLookupResolution(BaseModel):
    target: Literal["origin", "destination"]
    query: str
    candidates: list[RouteLookupCandidate]
