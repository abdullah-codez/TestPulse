"""
TestPulse — Pydantic v2 API Schemas
Used as data contracts for REST API responses, MCP tool payloads,
and inter-module communication.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Base schema mixin
# ---------------------------------------------------------------------------

class TestPulseBaseModel(BaseModel):
    """Base config for all TestPulse schemas."""

    __test__ = False

    model_config = ConfigDict(
        from_attributes=True,      # ORM mode — build from SQLAlchemy model instances
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(TestPulseBaseModel):
    """Response schema for GET /health."""

    status: str = "healthy"
    version: str
    environment: str
    db_accessible: bool


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

class RunConfig(TestPulseBaseModel):
    """Configuration for a TestPulse testing run."""

    test_scope: list[str] = Field(
        default=["unit"],
        description="Phases to execute: unit | integration | regression",
    )
    target_stack: str = Field(
        default="fastapi_sqlite",
        description="Backend architecture profile",
    )
    max_targets: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Max targets per phase (budget-aware)",
    )
    max_repair_retries: int = Field(default=3, ge=1, le=10)
    base_revision: str | None = Field(
        default=None,
        description="Git commit or snapshot label for regression baseline",
    )


class StartRunRequest(TestPulseBaseModel):
    """Request body / MCP input for testpulse/start_run."""

    workspace_path: str = Field(
        description="Absolute path to the client repository workspace"
    )
    config: RunConfig = Field(default_factory=RunConfig)


class StartRunResponse(TestPulseBaseModel):
    """Response from testpulse/start_run."""

    run_id: str
    status: str
    baseline_snapshot: str | None = None
    message: str = "Run created successfully"


class RunStatusResponse(TestPulseBaseModel):
    """Response from testpulse/get_status."""

    run_id: str
    status: str
    phase: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class RunSummary(TestPulseBaseModel):
    """Brief summary of a run for listing endpoints."""

    id: str
    status: str
    workspace_path: str
    created_at: datetime | None = None
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

class SnapshotSummary(TestPulseBaseModel):
    """Snapshot record summary."""

    id: str
    run_id: str
    snapshot_label: str
    created_at: datetime | None = None


class CheckpointRequest(TestPulseBaseModel):
    """Request body / MCP input for testpulse/create_checkpoint."""

    run_id: str
    note: str | None = None


class CheckpointResponse(TestPulseBaseModel):
    """Response from testpulse/create_checkpoint."""

    checkpoint_id: str
    snapshot_label: str
    modified_nodes: list[str] = Field(default_factory=list)
    blast_radius_nodes: list[str] = Field(default_factory=list)
    regression_scheduled: bool = False


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

class FindingSummary(TestPulseBaseModel):
    """A single defect finding."""

    id: str
    classification: str  # app_defect | test_defect | inconclusive
    severity: str | None = None
    title: str
    description: str
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    evidence_trace: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class GetResultsRequest(TestPulseBaseModel):
    """Request body / MCP input for testpulse/get_results."""

    run_id: str
    include_rca: bool = True
    classification_filter: str | None = None  # "app_defect" | "inconclusive" | None = all


class GetResultsResponse(TestPulseBaseModel):
    """Response from testpulse/get_results."""

    run_id: str
    status: str
    findings: list[FindingSummary] = Field(default_factory=list)
    rca_reports: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Behavior matrix & Context Bundle (Planner & Context Gatherer handoffs)
# ---------------------------------------------------------------------------

StrategyType = Literal["unit", "integration", "regression"]


class ContextBundle(TestPulseBaseModel):
    """Rich multi-strategy context bundle assembled for Planner & Writer handoff."""

    strategy: StrategyType
    target_node_id: str
    target_symbol: str
    source_file: str
    line_span: tuple[int, int]
    cyclomatic_complexity: int = 1
    focal_code: str = Field(
        description="The exact cAST chunk of the target node under test"
    )
    dependency_code: list[str] = Field(
        default_factory=list,
        description="Exact cAST chunks of linked callers/callees/schemas from Pipeline A",
    )
    descriptive_context: list[str] = Field(
        default_factory=list,
        description="Semantic doc/README rules and fixtures from Pipeline B",
    )
    mock_policy: dict[str, str] = Field(
        default_factory=dict,
        description="Explicit rules on what must vs. must not be mocked",
    )
    existing_fixtures: list[str] = Field(
        default_factory=list,
        description="Names/signatures of fixtures found in conftest.py, if any",
    )


class BehaviorCase(TestPulseBaseModel):
    """A discrete verifiable behavior case within a test plan."""

    id: str
    category: Literal["happy", "boundary", "negative"]
    description: str
    inputs: dict[str, Any] | str = Field(default_factory=dict)
    expected_outcome: str

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v: Any) -> str:
        s = str(v).lower().strip()
        if "happy" in s:
            return "happy"
        if "bound" in s or "edge" in s:
            return "boundary"
        if "neg" in s or "err" in s or "fail" in s or "except" in s:
            return "negative"
        return "happy"


class TestCase(TestPulseBaseModel):
    """Legacy test case schema."""

    name: str
    category: str
    inputs: dict[str, Any]
    expected: dict[str, Any]
    assertions: list[str]
    rationale: str


class BehaviorEntry(TestPulseBaseModel):
    """Legacy behavior entry schema."""

    id: str
    description: str
    evidence: str
    confidence: str
    test_cases: list[TestCase]


class MockBoundaries(TestPulseBaseModel):
    """What to mock vs. exercise for this test plan."""

    mock: list[str] = Field(default_factory=list)
    exercise_real: list[str] = Field(default_factory=list)


class BehaviorMatrix(TestPulseBaseModel):
    """Structured output from the Planner agent for a given target."""

    strategy: StrategyType
    target_node_id: str
    target_symbol: str
    cases: list[BehaviorCase] = Field(default_factory=list)
    mock_constraints: list[str] = Field(default_factory=list)
    uncovered_lines: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Test Synthesis & Validation (Writer & Validator handoffs)
# ---------------------------------------------------------------------------

class CandidateTest(TestPulseBaseModel):
    """Generated test code and associated dependencies from the Writer agent."""

    test_code: str = Field(description="Executable pytest test suite code")
    fixtures_needed: list[str] = Field(
        default_factory=list,
        description="Names of fixtures required by the generated test",
    )
    test_file_name: str | None = Field(
        default=None,
        description="Suggested target filename for the generated test",
    )


class ValidationResult(TestPulseBaseModel):
    """Verification outcome across Phase 1 (Internal Static AST) and Phase 2 (External Dynamic)."""

    is_valid: bool = Field(description="True if test passes all validation gates")
    failed_phase: Literal["internal", "external", "none"] = Field(
        default="none",
        description="Phase where failure occurred",
    )
    feedback: str = Field(
        default="",
        description="Detailed error, smell description, or traceback to feed back to Planner/Writer",
    )
    coverage_achieved: float = Field(
        default=0.0,
        description="Line/branch coverage percentage achieved by the test",
    )
    exit_code: int = Field(default=0, description="Process exit code from test runner")
    stderr: str = Field(default="", description="Stderr or traceback output from execution")
    mutants_killed: int = Field(default=0, description="Number of logic mutants killed in Gate 2")
    mutants_survived: int = Field(default=0, description="Number of logic mutants that survived")


