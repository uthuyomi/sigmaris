# 役割: 取り込みプレビュー API の Pydantic スキーマを定義する。

from typing import Literal

from pydantic import BaseModel, Field


class ImportCandidate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(alias="startTime", pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(alias="endTime", pattern=r"^\d{2}:\d{2}$")
    description: str | None = Field(default=None, max_length=2000)
    confidence: float | None = None


class ImportPreview(BaseModel):
    summary: str = Field(max_length=2000)
    candidates: list[ImportCandidate] = Field(max_length=100)


class ImageImportPreviewRequest(BaseModel):
    source_type: Literal["image"] = Field(alias="sourceType")
    source_label: str | None = Field(default=None, alias="sourceLabel", max_length=200)
    filename: str | None = Field(default=None, max_length=200)
    mime_type: str = Field(alias="mimeType", max_length=100)
    base64_data: str = Field(alias="base64Data", max_length=12_000_000)


class SheetImportPreviewRequest(BaseModel):
    source_type: Literal["sheet"] = Field(alias="sourceType")
    source_label: str | None = Field(default=None, alias="sourceLabel", max_length=200)
    sheet_title: str = Field(alias="sheetTitle", min_length=1, max_length=200)
    rows: list[list[str]] = Field(max_length=50)


ImportPreviewRequest = ImageImportPreviewRequest | SheetImportPreviewRequest
