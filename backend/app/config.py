# 役割: FastAPI バックエンドの環境設定をまとめる。

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ShiftPilotAI Backend"
    app_env: str = "development"
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:3000"
    google_maps_api_key: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-nano"
    openai_import_model: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    google_calendar_id: str = "primary"
    next_public_supabase_url: str | None = None
    next_public_supabase_publishable_key: str | None = None
    pro_plan_override_emails: str | None = None
    agent_secrets: str | None = None
    schedule_agent_base_url: str = "http://127.0.0.1:8000"
    schedule_agent_id: str = "sigmaris-orchestrator"
    schedule_agent_secret: str | None = None
    sigmaris_persona_path: str = "../docs/persona.md"
    sigmaris_rewrite_model: str | None = None
    sigmaris_guard_model: str | None = None

    model_config = SettingsConfigDict(
        env_file=(".env", "../frontend/.env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
