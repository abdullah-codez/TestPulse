"""
TestPulse — Main Application Entry Point
FastAPI REST & Dashboard API server running natively in host Python .venv.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from testpulse.api.health import router as health_router
from testpulse.api.runs import router as runs_router
from testpulse.core.config import settings
from testpulse.models.database import engine, init_db

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan context manager.
    Initializes database tables on startup and disposes connections on shutdown.
    """
    logger.info(
        "testpulse.startup",
        env=settings.env,
        db_path=str(settings.db_path),
        workspace=str(settings.workspace_dir),
    )
    # Ensure workspace and initialize SQLite database with WAL mode
    await init_db()
    yield
    logger.info("testpulse.shutdown")
    await engine.dispose()


app = FastAPI(
    title="TestPulse",
    description="Autonomous Agentic QA & Verification Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Enable CORS for local developer dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(health_router)
app.include_router(runs_router)


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root info endpoint."""
    return {
        "name": "TestPulse",
        "version": "0.1.0",
        "status": "online",
        "docs": "/docs",
    }


def run() -> None:
    """CLI runner for local development."""
    import uvicorn

    uvicorn.run(
        "testpulse.main:app",
        host=settings.host,
        port=settings.port,
        reload=(settings.env == "development"),
    )


if __name__ == "__main__":
    run()
