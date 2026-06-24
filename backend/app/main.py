# 役割: FastAPI アプリ本体とルーティングを構成する。

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes.agent import router as agent_router
from app.routes.app_data import router as app_data_router
from app.routes.chat import router as chat_router
from app.routes.google_tools import router as google_tools_router
from app.routes.import_preview import router as import_preview_router
from app.routes.mobility import router as mobility_router
from app.routes.orchestrator import router as orchestrator_router
from app.services.proactive.scheduler import shutdown_scheduler, startup_scheduler
from app.services.supabase_rest import (
    shutdown_supabase_http_client,
    startup_supabase_http_client,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await startup_supabase_http_client()
    startup_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()
        await shutdown_supabase_http_client()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mobility_router)
app.include_router(import_preview_router)
app.include_router(chat_router)
app.include_router(google_tools_router)
app.include_router(app_data_router)
app.include_router(agent_router)
app.include_router(orchestrator_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "shiftpilotai-backend"}


@app.get(f"{settings.api_prefix}/health")
async def api_health() -> dict[str, str]:
    return {"status": "ok", "service": "shiftpilotai-backend", "scope": "api"}
