from __future__ import annotations

# 役割: Google API クライアント共通処理を提供する。

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import settings
from app.schemas.google_tools import GoogleProviderTokens


def _require_google_oauth_config() -> tuple[str, str]:
    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError("Google OAuth environment variables are not fully configured for backend.")
    return settings.google_client_id, settings.google_client_secret


def build_google_credentials(tokens: GoogleProviderTokens) -> Credentials:
    client_id, client_secret = _require_google_oauth_config()
    if not tokens.access_token and not tokens.refresh_token:
        raise RuntimeError("Google OAuth token is not available.")

    return Credentials(
        token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
    )


def create_calendar_client(tokens: GoogleProviderTokens):
    credentials = build_google_credentials(tokens)
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def create_sheets_client(tokens: GoogleProviderTokens):
    credentials = build_google_credentials(tokens)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)
