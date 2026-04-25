from __future__ import annotations

# 役割: Google Sheets のプレビュー読み取りを扱う。

import re

from app.schemas.google_tools import GoogleProviderTokens
from app.services.google_api import create_sheets_client


def extract_spreadsheet_id(url: str) -> str | None:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return match.group(1) if match else None


def read_google_sheet_preview(*, tokens: GoogleProviderTokens, url: str):
    spreadsheet_id = extract_spreadsheet_id(url)
    if not spreadsheet_id:
        raise RuntimeError("Could not extract spreadsheetId from Google Sheets URL.")

    sheets = create_sheets_client(tokens)
    spreadsheet = (
        sheets.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, includeGridData=False)
        .execute()
    )
    first_sheet_title = (
        spreadsheet.get("sheets", [{}])[0]
        .get("properties", {})
        .get("title")
    )
    if not first_sheet_title:
        raise RuntimeError("Could not determine the first sheet title.")

    values = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"{first_sheet_title}!A1:Z50",
        )
        .execute()
    )

    return {
        "spreadsheetId": spreadsheet_id,
        "sheetTitle": first_sheet_title,
        "rows": values.get("values", []),
    }
