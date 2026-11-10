"""
TestPulse — SQLAlchemy Database Models & Engine
Uses SQLite (aiosqlite) with WAL mode for concurrent access from FastAPI and MCP server.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, event, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from testpulse.core.config import settings

# ---------------------------------------------------------------------------
# Engine — created lazily once settings are resolved
# ---------------------------------------------------------------------------

def _create_engine():  # type: ignore[return]
    """
    Build the async SQLAlchemy engine for SQLite with WAL mode.

    WAL mode (Write-Ahead Logging) allows concurrent readers alongside a writer,
    which is essential because both the FastAPI HTTP server and the MCP stdio
    server access the same .testpulse/testpulse.db simultaneously.

    busy_timeout=5000ms prevents immediate "database is locked" errors by
    retrying for up to 5 seconds before raising an exception.
    """
    engine = create_async_engine(
        settings.db_url,
        echo=(settings.env == "development"),
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(dbapi_conn: Any, connection_record: Any) -> None:  # noqa: ANN401
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine = _create_engine()

# Session factory — use with `async with AsyncSessionLocal() as session:`
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Run(Base):
    """
    A single TestPulse execution run.
    Created when testpulse/start_run is called via MCP.
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        # Valid values: pending | analyzing | unit_testing | integration_testing
        #               | regression_testing | browser_testing | rca | complete | failed
    )
    workspace_path: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    snapshots: Mapped[list[Snapshot]] = relationship(back_populates="run", cascade="all, delete-orphan")
    test_plans: Mapped[list[TestPlan]] = relationship(back_populates="run", cascade="all, delete-orphan")
    findings: Mapped[list[Finding]] = relationship(back_populates="run", cascade="all, delete-orphan")
    browser_sessions: Mapped[list[BrowserSession]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Snapshot(Base):
    """
    A Git-free snapshot checkpoint of the client repository.
    T0 = initial baseline; T1, T2, ... = post-fix checkpoints.
    """

    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    snapshot_label: Mapped[str] = mapped_column(String(16), nullable=False)  # "T0", "T1", ...
    graph_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # Path to on-disk graph.json
    ast_hashes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)  # {node_id: sha256}
    diff_against_previous: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    run: Mapped[Run] = relationship(back_populates="snapshots")
    test_plans: Mapped[list[TestPlan]] = relationship(back_populates="snapshot")


class TestPlan(Base):
    """
    The planned behavior matrix for a specific target symbol.
    Generated by the Planner agent for a given snapshot and strategy.
    """

    __test__ = False
    __tablename__ = "test_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("snapshots.id", ondelete="SET NULL"), nullable=True
    )
    strategy: Mapped[str] = mapped_column(String(16), nullable=False)  # "unit" | "integration" | "regression"
    target_symbol: Mapped[str] = mapped_column(Text, nullable=False)
    target_file: Mapped[str] = mapped_column(Text, nullable=False)
    behavior_matrix: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    run: Mapped[Run] = relationship(back_populates="test_plans")
    snapshot: Mapped[Snapshot | None] = relationship(back_populates="test_plans")
    generated_tests: Mapped[list[GeneratedTest]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class GeneratedTest(Base):
    """
    A single generated test case, its execution result, and validation outcome.
    Tracks the anti-shallow validation gates.
    """

    __tablename__ = "generated_tests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("test_plans.id", ondelete="CASCADE"), nullable=False)
    target_behavior_id: Mapped[str | None] = mapped_column(Text, nullable=True)  # Behavior ID from behavior_matrix
    test_code: Mapped[str] = mapped_column(Text, nullable=False)
    test_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(default=1)
    validation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending"
        # Values: pending | valid | invalid_repaired | rejected | inconclusive
    )
    # Coverage metrics
    target_coverage_pct: Mapped[float | None] = mapped_column(nullable=True)
    # Gate 1: AST smell findings
    ast_smells: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Gate 2: Mutation testing results
    mutation_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
        # Structure: {mutants_killed: int, mutants_survived: int, surviving_diffs: [...]}
    )
    # Raw sandbox execution result
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    plan: Mapped[TestPlan] = relationship(back_populates="generated_tests")
    finding: Mapped[Finding | None] = relationship(back_populates="test", uselist=False)


class Finding(Base):
    """
    A confirmed defect finding or inconclusive result from test execution.
    Every finding must have evidence (file + line range + assertion trace).
    """

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    test_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("generated_tests.id", ondelete="SET NULL"), nullable=True
    )
    classification: Mapped[str] = mapped_column(
        String(16), nullable=False
        # Values: app_defect | test_defect | inconclusive
    )
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)  # critical | major | minor
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_start: Mapped[int | None] = mapped_column(nullable=True)
    line_end: Mapped[int | None] = mapped_column(nullable=True)
    evidence_trace: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    run: Mapped[Run] = relationship(back_populates="findings")
    test: Mapped[GeneratedTest | None] = relationship(back_populates="finding")


class BrowserSession(Base):
    """
    A Component 2 Playwright browser testing session.
    Stores the generated scenario script, diagnostics, and backend logs
    for correlation by Component 3 (RCA Engine).
    """

    __tablename__ = "browser_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    scenario_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # Playwright scenario script content and its file path
    script_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Browser-side diagnostics
    console_logs: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    network_errors: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # Backend-side stack traces (from FastAPI server logs during scenario)
    backend_logs: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    screenshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    run: Mapped[Run] = relationship(back_populates="browser_sessions")
    rca_reports: Mapped[list[RCAReport]] = relationship(back_populates="browser_session", cascade="all, delete-orphan")


class RCAReport(Base):
    """
    A Root-Cause Analysis report produced by Component 3.
    Linked to the browser session that triggered it and optionally to a code finding.
    """

    __tablename__ = "rca_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    browser_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False
    )
    finding_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("findings.id", ondelete="SET NULL"), nullable=True
    )
    failure_summary: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause_layer: Mapped[str | None] = mapped_column(
        Text, nullable=True
        # Values: frontend_ui | api_route | business_logic | database
    )
    suspected_symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspected_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    cross_layer_trace: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    suggested_fix_hypothesis: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    browser_session: Mapped[BrowserSession] = relationship(back_populates="rca_reports")


# ---------------------------------------------------------------------------
# DB Lifecycle helpers
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """
    Create all tables if they don't exist.
    Called once at application startup. Idempotent — safe to run on every boot.
    """
    settings.ensure_workspace()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — yields an async database session.

    Usage:
        @app.get("/runs")
        async def list_runs(session: AsyncSession = Depends(get_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        yield session
