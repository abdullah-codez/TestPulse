"""Sample FastAPI application entry point fixture."""

from __future__ import annotations

from fastapi import FastAPI

from tests.fixtures.sample_fastapi.routes.orders import router as orders_router

app = FastAPI(
    title="Sample E-Commerce API",
    description="Fixture application for TestPulse AST and graph analysis verification.",
    version="0.1.0",
)

app.include_router(orders_router)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Health check endpoint for the fixture app."""
    return {"status": "ok", "app": "Sample E-Commerce API"}
