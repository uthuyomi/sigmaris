# 役割: FastAPI バックエンドの環境設定をまとめる。

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Sigmaris Backend"
    app_env: str = "development"
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:3000"
    google_maps_api_key: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"           # 通常会話・ルーティング
    openai_nano_model: str = "gpt-5.4-nano"       # 記憶抽出・要約・分類
    openai_advanced_model: str = "gpt-5.5"        # 自己反省・設計・週次レビュー
    openai_import_model: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    google_calendar_id: str = "primary"
    next_public_supabase_url: str | None = None
    next_public_supabase_publishable_key: str | None = None
    supabase_service_role_key: str | None = None
    pro_plan_override_emails: str | None = None
    agent_secrets: str | None = None
    schedule_agent_base_url: str = "http://127.0.0.1:8000"
    schedule_agent_id: str = "sigmaris-orchestrator"
    schedule_agent_secret: str | None = None
    sigmaris_persona_path: str = "../docs/persona.md"
    sigmaris_rewrite_model: str | None = None
    sigmaris_guard_model: str | None = None
    sigmaris_reflect_model: str | None = None
    sigmaris_timezone: str = "Asia/Tokyo"
    sigmaris_recent_message_window: int = 40
    sigmaris_user_jwt: str | None = None
    sigmaris_refresh_token: str | None = None
    sigmaris_google_access_token: str | None = None
    sigmaris_surface_inquiry_questions: bool = False
    pushover_user_key: str | None = None
    pushover_app_token: str | None = None
    proactive_enabled: bool = True
    local_llm_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b"
    ollama_embed_model: str = "nomic-embed-text"
    openai_embedding_model: str = "text-embedding-3-small"
    eval_generation_model: str = "gpt-5.4-mini"   # Phase C-mini testset question generation (OpenAI fallback)
    eval_judge_model: str | None = None           # Phase C-full LLM-as-a-Judge (None -> openai_advanced_model)
    # Phase C-full: dedicated Supabase account for LongMemEval/LoCoMo ingestion,
    # deliberately separate from sigmaris_user_jwt/sigmaris_refresh_token (the
    # real user's own credentials) so public-benchmark conversation data can
    # never land in the same user_fact_items rows as 海星さん's real memories.
    # See backend/app/services/bench_auth.py.
    sigmaris_eval_bench_refresh_token: str | None = None
    sigmaris_eval_bench_user_jwt: str | None = None
    x_api_key: str | None = None
    x_api_secret: str | None = None
    x_access_token: str | None = None
    x_access_token_secret: str | None = None
    x_enabled: bool = False
    sigmaris_launch_date: str | None = None
    github_token: str | None = None
    github_repo: str | None = None
    self_improvement_enabled: bool = False
    health_sync_enabled: bool = False
    news_api_key: str | None = None
    research_enabled: bool = False
    agent_registry_json: str | None = None

    model_config = SettingsConfigDict(
        env_file=(".env", "../frontend/.env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
