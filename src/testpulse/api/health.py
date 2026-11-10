"""
TestPulse — Health API Endpoint
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter
from sqlalchemy import text

from testpulse.core.config import settings
from testpulse.models.database import AsyncSessionLocal
from testpulse.models.schemas import HealthResponse

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the operational status of the TestPulse API and database.",
)
async def health_check() -> HealthResponse:
    """
    Returns healthy when the FastAPI process is running and the SQLite database
    is accessible. This is the primary liveness check for Milestone 0.
    """
    db_ok = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        logger.exception("health_check.db_error")

    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        version="0.1.0",
        environment=settings.env,
        db_accessible=db_ok,
    )
