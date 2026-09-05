"""ReconGuard API.

Startup contract: the application must come up and serve every endpoint with
no LLM provider configured, no API keys present, and no external service
reachable. The deterministic engine is the whole product at this stage.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    core_routes,
    intelligence_routes,
    ops_routes,
    record_routes,
)
from app.core.config import get_settings
from app.db.init_db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
)
logger = logging.getLogger("reconguard")

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info(
        "ReconGuard %s ready | engine=%s | db=%s | ai_provider=%s (engine does not "
        "require it)",
        settings.system_version,
        settings.reconciliation.engine_version,
        settings.database_url.split(":")[0],
        settings.ai_provider,
    )
    yield


app = FastAPI(
    lifespan=lifespan,
    title="ReconGuard API",
    version=settings.system_version,
    description=(
        "Deterministic reconciliation. Verified AI. Zero silent exceptions.\n\n"
        "Every figure this API returns is computed from actual source records. "
        "No metric is hardcoded, no confidence score is fabricated, and no "
        "reconciliation result is produced by a language model."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(core_routes.router, prefix=settings.api_prefix)
app.include_router(record_routes.router, prefix=settings.api_prefix)
app.include_router(ops_routes.router, prefix=settings.api_prefix)
app.include_router(intelligence_routes.router, prefix=settings.api_prefix)


@app.get("/", tags=["system"])
def root() -> dict:
    return {
        "name": settings.app_name,
        "tagline": "Deterministic reconciliation. Verified AI. Zero silent exceptions.",
        "version": settings.system_version,
        "docs": "/docs",
        "api": settings.api_prefix,
    }
