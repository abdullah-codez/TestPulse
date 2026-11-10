"""
TestPulse — Pytest Fixtures
Provides isolated async test sessions and test client for FastAPI.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from testpulse.main import app
from testpulse.models.database import Base, get_session


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Specify anyio backend as asyncio."""
    return "asyncio"


@pytest_asyncio.fixture(scope="function")
async def test_db_session(tmp_path: Path) -> AsyncGenerator[AsyncSession, None]:
    """
    Creates an isolated temporary SQLite database for each test function,
    enforcing WAL mode and busy_timeout=5000ms.
    """
    db_file = tmp_path / "testpulse_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    engine = create_async_engine(
        db_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(dbapi_conn: Any, connection_record: Any) -> None:  # noqa: ANN401
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(test_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTP test client bound to FastAPI app with overridden database session.
    """
    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield test_db_session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
