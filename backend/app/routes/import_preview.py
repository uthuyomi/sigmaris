# 役割: 予定取り込みプレビューの FastAPI HTTP ルートを定義する。

from fastapi import APIRouter, Header, HTTPException

from app.schemas.import_preview import (
    ImageImportPreviewRequest,
    ImportPreviewRequest,
    SheetImportPreviewRequest,
)
from app.services.supabase_rest import get_current_user
from app.services.import_extract import (
    extract_schedule_from_image,
    extract_schedule_from_sheet_rows,
)

router = APIRouter(prefix="/api/import", tags=["import"])


def _require_jwt(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Missing bearer token."})
    return authorization.removeprefix("Bearer ").strip()


@router.post("/preview")
async def import_preview(
    input: ImportPreviewRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    await get_current_user(jwt)

    try:
        if isinstance(input, SheetImportPreviewRequest):
            extracted = await extract_schedule_from_sheet_rows(
                sheet_title=input.sheet_title,
                rows=input.rows,
            )
            return {
                "sourceType": "sheet",
                "sourceLabel": input.source_label or input.sheet_title,
                "extracted": extracted.model_dump(by_alias=True),
            }

        if isinstance(input, ImageImportPreviewRequest):
            extracted = await extract_schedule_from_image(
                mime_type=input.mime_type,
                base64_data=input.base64_data,
                filename=input.filename or input.source_label,
            )
            return {
                "sourceType": "image",
                "sourceLabel": input.source_label or input.filename or "image",
                "extracted": extracted.model_dump(by_alias=True),
            }

        raise HTTPException(status_code=400, detail={"error": "Unsupported import payload."})
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
