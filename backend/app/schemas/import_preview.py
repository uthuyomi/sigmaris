# 役割: 取り込みプレビュー API の Pydantic スキーマを定義する。

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ImportCandidate(BaseModel):
    # IMPORT_EXTRACTION_REDESIGN: 予定全般の画像/テキストから抽出する候補。
    # 終日(all_day)・終了時刻なし・場所・読み取り根拠(evidence)に対応し、
    # 時刻は任意(None 可)にした。date は必須のまま。
    title: str = Field(min_length=1, max_length=120)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str | None = Field(default=None, alias="startTime", pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(default=None, alias="endTime", pattern=r"^\d{2}:\d{2}$")
    all_day: bool = Field(default=False, alias="allDay")
    location: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    # A-4: その予定を読み取った元テキスト/ラベルの引用(画像内の「7/25 早番
    # 9:00-15:00」等)。根拠を引用できない候補は抽出プロンプトで出させない。
    evidence: str | None = Field(default=None, max_length=500)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_time_consistency(self) -> "ImportCandidate":
        # all_day=True のときは時刻を持たない(終日)。all_day=False のときは
        # 少なくとも start_time が必要(時刻ありイベント)。不整合な組み合わせを
        # 弾く。end_time は任意(終了未定なら None のまま登録側で既定を補う)。
        if self.all_day:
            if self.start_time is not None or self.end_time is not None:
                raise ValueError("all-day candidate must not carry start/end times")
        else:
            if self.start_time is None:
                raise ValueError("timed candidate requires startTime (or set allDay=true)")
        return self


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
    rows: list[list[str]] = Field(max_length=100)


ImportPreviewRequest = ImageImportPreviewRequest | SheetImportPreviewRequest
