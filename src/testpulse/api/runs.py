"""
TestPulse — Runs API Endpoint (Stub for M0)
Full implementation deferred to Milestone 6 (Orchestrator + Multi-Target Pipeline).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/runs", tags=["runs"])


class RunStub(BaseModel):
    id: str
    status: str
    message: str


@router.get(
    "/",
    response_model=list[RunStub],
    summary="List runs (stub)",
    description="Placeholder endpoint. Full implementation in Milestone 6.",
)
async def list_runs() -> list[RunStub]:
    """Returns an empty list in M0. Populated in Milestone 6."""
    return []


@router.get(
    "/{run_id}",
    response_model=RunStub,
    summary="Get run (stub)",
    description="Placeholder endpoint. Full implementation in Milestone 6.",
)
async def get_run(run_id: str) -> RunStub:
    """Stub endpoint for M0. Full implementation in Milestone 6."""
    return RunStub(id=run_id, status="stub", message="Full implementation in Milestone 6")
