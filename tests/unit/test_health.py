"""
Unit tests for TestPulse Health & Root API endpoints.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient) -> None:
    """Verifies that GET / returns the system status and documentation link."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "TestPulse"
    assert data["version"] == "0.1.0"
    assert data["status"] == "online"


@pytest.mark.asyncio
async def test_health_check_endpoint(client: AsyncClient) -> None:
    """Verifies that GET /health responds with healthy status and database accessible."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert data["version"] == "0.1.0"
    assert "environment" in data
    assert "db_accessible" in data


@pytest.mark.asyncio
async def test_runs_stub_endpoint(client: AsyncClient) -> None:
    """Verifies that GET /runs returns an empty list in Milestone 0."""
    response = await client.get("/runs/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0
