"""
TestPulse — Unit Tests for Milestone 4: Greenfield Test Synthesis & Dual-Phase Validator
Verifies:
1. Validator.run_internal_validation (Phase 1 Static AST):
   - Catches and rejects tests with missing assertions (zero assertions).
   - Catches and rejects tautological assertions (assert True, assert res is not None, assert 1 == 1).
   - Catches and rejects conditional assertions (assert inside if/loops).
   - Catches and rejects swallowed exceptions (try...except: pass).
   - Accepts well-formed assertions and pytest.raises checks.
2. Validator.run_external_validation (Phase 2 Dynamic Gates):
   - Sandbox execution error reporting (Problem A).
   - Unit dynamic gate: Targeted mutation testing (mutants killed vs. survived).
   - Integration dynamic gate: 3-run flakiness check (state leakage detection).
   - Regression dynamic gate: Fail-to-Pass check (must fail on T0, pass on T1).
3. TestWriter.synthesize:
   - Synthesizes CandidateTest with markdown fence stripping and fixture detection.
4. PipelineOrchestrator / run_pipeline:
   - Internal validation failure loops back to Planner mock with feedback and increments retry counter.
   - External validation failure loops back to Writer mock with stderr and increments retry counter.
   - Success path returns accepted status with candidate and validation result.
   - Bounded loop terminates and returns rejected status when max retries exceeded.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from testpulse.llm.router import LLMRouter
from testpulse.models.schemas import (
    BehaviorCase,
    BehaviorMatrix,
    CandidateTest,
    ContextBundle,
    ValidationResult,
)
from testpulse.pipeline.orchestrator import run_pipeline
from testpulse.pipeline.validator import Validator
from testpulse.pipeline.writer import TestWriter, extract_fixtures_needed, extract_python_code

# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

def _make_dummy_bundle(strategy: str = "unit") -> ContextBundle:
    return ContextBundle(
        strategy=strategy,  # type: ignore
        target_node_id="sample::calculate_discount",
        target_symbol="calculate_discount",
        source_file="sample.py",
        line_span=(10, 25),
        cyclomatic_complexity=4,
        focal_code="def calculate_discount(price: float, is_vip: bool) -> float:\n    if is_vip and price > 100.0:\n        return price * 0.8\n    return price",
        dependency_code=[],
        descriptive_context=[],
        mock_policy={"isolation": "isolate target in memory"},
        existing_fixtures=["db_session"],
    )


def _make_dummy_matrix(strategy: str = "unit") -> BehaviorMatrix:
    return BehaviorMatrix(
        strategy=strategy,  # type: ignore
        target_node_id="sample::calculate_discount",
        target_symbol="calculate_discount",
        cases=[
            BehaviorCase(
                id="CASE-1",
                category="happy",
                description="VIP discount applied over 100",
                inputs={"price": 200.0, "is_vip": True},
                expected_outcome="returns 160.0",
            )
        ],
        mock_constraints=["Never mock calculate_discount"],
        uncovered_lines=[12],
    )


# ---------------------------------------------------------------------------
# 1. Phase 1 Static AST Smell Detection Tests
# ---------------------------------------------------------------------------

def test_internal_validation_rejects_zero_assertions() -> None:
    """Verifies that a test function without any assertions is detected and rejected."""
    code = """
def test_calculate_discount_missing():
    price = 100.0
    vip = True
    result = price * 0.8
"""
    candidate = CandidateTest(test_code=code)
    res = Validator.run_internal_validation(candidate)

    assert not res.is_valid
    assert res.failed_phase == "internal"
    assert "Missing Assertions" in res.feedback
    assert "zero assertions" in res.feedback


def test_internal_validation_rejects_assert_true() -> None:
    """Verifies that tautological `assert True` is detected and rejected."""
    code = """
def test_tautology_true():
    assert True
"""
    candidate = CandidateTest(test_code=code)
    res = Validator.run_internal_validation(candidate)

    assert not res.is_valid
    assert res.failed_phase == "internal"
    assert "Tautological Assertion" in res.feedback
    assert "assert True" in res.feedback


def test_internal_validation_rejects_assert_is_not_none() -> None:
    """Verifies that shallow existence assertion `assert x is not None` is rejected."""
    code = """
def test_shallow_not_none():
    res = calculate_discount(100.0, True)
    assert res is not None
"""
    candidate = CandidateTest(test_code=code)
    res = Validator.run_internal_validation(candidate)

    assert not res.is_valid
    assert res.failed_phase == "internal"
    assert "Tautological Assertion" in res.feedback
    assert "shallow existence check" in res.feedback


def test_internal_validation_rejects_assert_neq_none() -> None:
    """Verifies that `assert x != None` is also rejected as a shallow existence check."""
    code = """
def test_shallow_neq_none():
    res = calculate_discount(100.0, True)
    assert res != None
"""
    candidate = CandidateTest(test_code=code)
    res = Validator.run_internal_validation(candidate)

    assert not res.is_valid
    assert res.failed_phase == "internal"
    assert "shallow existence check" in res.feedback


def test_internal_validation_rejects_identical_operands() -> None:
    """Verifies that `assert 1 == 1` is detected as comparing identical expressions."""
    code = """
def test_identical_comparison():
    assert 1 == 1
"""
    candidate = CandidateTest(test_code=code)
    res = Validator.run_internal_validation(candidate)

    assert not res.is_valid
    assert res.failed_phase == "internal"
    assert "comparing identical expressions" in res.feedback


def test_internal_validation_rejects_conditional_assertions() -> None:
    """Verifies that assertions wrapped inside if-blocks or loops are rejected."""
    code = """
def test_conditional():
    res = calculate_discount(150.0, True)
    if res > 100:
        assert res == 120.0
"""
    candidate = CandidateTest(test_code=code)
    res = Validator.run_internal_validation(candidate)

    assert not res.is_valid
    assert res.failed_phase == "internal"
    assert "Conditional Assertion" in res.feedback
    assert "nested inside an 'if'" in res.feedback


def test_internal_validation_rejects_swallowed_exceptions() -> None:
    """Verifies that try...except: pass is detected as swallowed exception."""
    code = """
def test_swallowed():
    try:
        calculate_discount(-10.0, False)
    except ValueError:
        pass
"""
    candidate = CandidateTest(test_code=code)
    res = Validator.run_internal_validation(candidate)

    assert not res.is_valid
    assert res.failed_phase == "internal"
    assert "Swallowed Exception" in res.feedback
    assert "with pytest.raises" in res.feedback


def test_internal_validation_accepts_clean_assertions() -> None:
    """Verifies that valid, concrete assertions pass Phase 1 cleanly."""
    code = """
import pytest

def test_calculate_discount_valid():
    assert calculate_discount(200.0, True) == 160.0

def test_negative_price_raises():
    with pytest.raises(ValueError):
        calculate_discount(-10.0, False)
"""
    candidate = CandidateTest(test_code=code)
    res = Validator.run_internal_validation(candidate)

    assert res.is_valid
    assert res.failed_phase == "none"
    assert res.feedback.startswith("Phase 1 Static AST validation passed")


# ---------------------------------------------------------------------------
# 2. Phase 2 External Validation & Dynamic Gates Tests
# ---------------------------------------------------------------------------

def test_external_validation_reports_sandbox_execution_error() -> None:
    """Verifies that compilation or syntax/runtime errors in the sandbox return Problem A feedback."""
    candidate = CandidateTest(test_code="def test_broken(): assert 1 == 2")

    def mock_runner(test_code: str, workspace_path: Any) -> tuple[int, str, float]:
        return 1, "AssertionError: assert 1 == 2\n + where 1 = 1 and 2 = 2", 0.0

    res = Validator.run_external_validation(
        candidate=candidate,
        strategy="unit",
        runner_fn=mock_runner,
    )

    assert not res.is_valid
    assert res.failed_phase == "external"
    assert res.exit_code == 1
    assert "Sandbox execution failed with exit code 1" in res.feedback
    assert "AssertionError" in res.feedback


def test_external_validation_unit_mutation_killed() -> None:
    """Verifies that when mutants are killed (test fails on mutated code), unit test is accepted."""
    candidate = CandidateTest(test_code="def test_ok(): assert add(2, 3) == 5")
    focal = "def add(a, b):\n    if a > 0:\n        return a + b\n    return b"

    call_count = 0

    def mock_runner(test_code: str, workspace_path: Any) -> tuple[int, str, float]:
        nonlocal call_count
        call_count += 1
        # Run 1: original code -> passes
        if call_count == 1:
            return 0, "1 passed in 0.01s", 100.0
        # Subsequent runs: mutated code -> fails (mutant killed!)
        return 1, "AssertionError: mutated code failed test", 0.0

    res = Validator.run_external_validation(
        candidate=candidate,
        strategy="unit",
        focal_code=focal,
        runner_fn=mock_runner,
    )

    assert res.is_valid
    assert res.failed_phase == "none"
    assert res.mutants_killed > 0
    assert res.mutants_survived == 0
    assert "All" in res.feedback and "mutants killed" in res.feedback


def test_external_validation_unit_mutation_survived_rejects() -> None:
    """Verifies that when a mutant survives (test still passes on mutated code), test is rejected."""
    candidate = CandidateTest(test_code="def test_shallow(): assert add(2, 3) > 0")
    focal = "def add(a, b):\n    if a > 0:\n        return a + b\n    return b"

    def mock_runner(test_code: str, workspace_path: Any) -> tuple[int, str, float]:
        # Always passes, even on mutated code!
        return 0, "1 passed in 0.01s", 100.0

    res = Validator.run_external_validation(
        candidate=candidate,
        strategy="unit",
        focal_code=focal,
        runner_fn=mock_runner,
    )

    assert not res.is_valid
    assert res.failed_phase == "external"
    assert res.mutants_survived > 0
    assert "Targeted Mutation Failed" in res.feedback
    assert "mutant(s) survived" in res.feedback


def test_external_validation_integration_flakiness_rejected() -> None:
    """Verifies that an integration test that passes on run 1 but fails on run 2 is rejected."""
    candidate = CandidateTest(test_code="def test_integration(): client.post('/items')")
    call_count = 0

    def mock_runner(test_code: str, workspace_path: Any) -> tuple[int, str, float]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return 0, "run 1 passed", 100.0
        # Fails on run 2 due to DB unique constraint / state leak
        return 1, "IntegrityError: UNIQUE constraint failed: items.id", 0.0

    res = Validator.run_external_validation(
        candidate=candidate,
        strategy="integration",
        runner_fn=mock_runner,
    )

    assert not res.is_valid
    assert res.failed_phase == "external"
    assert "Flakiness Check Failed" in res.feedback
    assert "failed on run 2" in res.feedback
    assert "database state leakage" in res.feedback


def test_external_validation_integration_3_runs_pass() -> None:
    """Verifies that an integration test that passes all 3 runs is accepted."""
    candidate = CandidateTest(test_code="def test_integration(): client.post('/items')")
    runs = 0

    def mock_runner(test_code: str, workspace_path: Any) -> tuple[int, str, float]:
        nonlocal runs
        runs += 1
        return 0, f"run {runs} passed", 100.0

    res = Validator.run_external_validation(
        candidate=candidate,
        strategy="integration",
        runner_fn=mock_runner,
    )

    assert res.is_valid
    assert res.failed_phase == "none"
    assert runs == 3
    assert "All 3 execution runs succeeded" in res.feedback


def test_external_validation_regression_f2p_rejects_if_passes_on_t0() -> None:
    """Verifies that regression test is rejected if it passes on buggy snapshot T0."""
    candidate = CandidateTest(test_code="def test_reproducer(): pass")

    def mock_runner(test_code: str, workspace_path: Any) -> tuple[int, str, float]:
        # Passes on T0 (buggy code)
        return 0, "passed on buggy code", 100.0

    res = Validator.run_external_validation(
        candidate=candidate,
        strategy="regression",
        t0_snapshot_path="snapshots/t0",
        t1_snapshot_path="snapshots/t1",
        runner_fn=mock_runner,
    )

    assert not res.is_valid
    assert res.failed_phase == "external"
    assert "Fail-to-Pass Check Failed" in res.feedback
    assert "passed on pre-fix snapshot T0" in res.feedback


def test_external_validation_regression_f2p_succeeds() -> None:
    """Verifies that regression test passes when it fails on T0 and passes on T1."""
    candidate = CandidateTest(test_code="def test_reproducer(): assert fixed_bug()")
    call_count = 0

    def mock_runner(test_code: str, workspace_path: Any) -> tuple[int, str, float]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Initial run on baseline passes
            return 0, "initial run passed", 100.0
        if call_count == 2:
            # T0 run fails (reproduces pre-fix bug)
            return 1, "AssertionError: Bug reproduced on T0", 0.0
        # T1 run passes (verifies fix)
        return 0, "Passed on T1", 100.0

    res = Validator.run_external_validation(
        candidate=candidate,
        strategy="regression",
        t0_snapshot_path="snapshots/t0",
        t1_snapshot_path="snapshots/t1",
        runner_fn=mock_runner,
    )

    assert res.is_valid
    assert res.failed_phase == "none"
    assert "Fail-to-Pass Check Passed" in res.feedback


# ---------------------------------------------------------------------------
# 3. TestWriter Agent Tests
# ---------------------------------------------------------------------------

def test_extract_python_code_and_fixtures() -> None:
    """Verifies markdown fence stripping and fixture parameter extraction."""
    markdown_wrapped = """```python
import pytest

def test_create_order(client, db_session):
    assert True
```"""
    code = extract_python_code(markdown_wrapped)
    assert code.startswith("import pytest")
    assert "assert True" in code
    assert "```" not in code

    fixtures = extract_fixtures_needed(code)
    assert fixtures == ["client", "db_session"]


def test_test_writer_synthesize() -> None:
    """Verifies TestWriter.synthesize completes via mocked router and produces CandidateTest."""
    bundle = _make_dummy_bundle()
    matrix = _make_dummy_matrix()

    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = """```python
import pytest

def test_calculate_discount_vip():
    res = calculate_discount(200.0, True)
    assert res == 160.0
```"""
    mock_resp.choices = [mock_choice]

    mock_router = MagicMock(spec=LLMRouter)
    mock_router.complete.return_value = mock_resp

    candidate = TestWriter.synthesize(bundle, matrix, router=mock_router)

    assert isinstance(candidate, CandidateTest)
    assert "def test_calculate_discount_vip" in candidate.test_code
    assert "assert res == 160.0" in candidate.test_code
    assert candidate.test_file_name == "test_unit_calculate_discount.py"
    mock_router.complete.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Pipeline Orchestrator & Loop-Back Tests
# ---------------------------------------------------------------------------

def test_orchestrator_happy_path() -> None:
    """Verifies happy path where all gates pass on the very first attempt."""
    bundle = _make_dummy_bundle()
    matrix = _make_dummy_matrix()
    candidate = CandidateTest(test_code="def test_ok(): assert 2 + 2 == 4")

    mock_planner = MagicMock()
    mock_planner.generate_plan.return_value = matrix

    mock_writer = MagicMock()
    mock_writer.synthesize.return_value = candidate

    mock_validator = MagicMock()
    mock_validator.run_internal_validation.return_value = ValidationResult(
        is_valid=True,
        failed_phase="none",
        feedback="AST clean",
    )
    mock_validator.run_external_validation.return_value = ValidationResult(
        is_valid=True,
        failed_phase="none",
        feedback="Sandbox clean",
        coverage_achieved=100.0,
    )

    result = run_pipeline(
        target_node_id="sample::calculate_discount",
        strategy="unit",
        bundle=bundle,
        planner_cls=mock_planner,
        writer_cls=mock_writer,
        validator_cls=mock_validator,
    )

    assert result["status"] == "accepted"
    assert result["total_attempts"] == 1
    assert result["internal_retries"] == 0
    assert result["external_retries"] == 0
    assert mock_planner.generate_plan.call_count == 1
    assert mock_writer.synthesize.call_count == 1


def test_orchestrator_internal_loopback_increments_counter() -> None:
    """
    Verifies that an internal validation failure (AST smell) increments the
    retry counter and loops back to the Planner mock with feedback.
    """
    bundle = _make_dummy_bundle()
    matrix = _make_dummy_matrix()

    # Candidate 1 has assert True (smell)
    bad_candidate = CandidateTest(test_code="def test_bad(): assert True")
    # Candidate 2 has concrete assertion
    good_candidate = CandidateTest(test_code="def test_good(): assert 2 + 2 == 4")

    mock_planner = MagicMock()
    mock_planner.generate_plan.return_value = matrix

    mock_writer = MagicMock()
    # Writer returns bad on first call, good on second
    mock_writer.synthesize.side_effect = [bad_candidate, good_candidate]

    mock_validator = MagicMock()
    # Internal validator rejects on attempt 1, passes on attempt 2
    mock_validator.run_internal_validation.side_effect = [
        ValidationResult(
            is_valid=False,
            failed_phase="internal",
            feedback="Line 2 contains trivial tautology: assert True.",
        ),
        ValidationResult(
            is_valid=True,
            failed_phase="none",
            feedback="AST clean.",
        ),
    ]
    mock_validator.run_external_validation.return_value = ValidationResult(
        is_valid=True,
        failed_phase="none",
        feedback="Sandbox clean.",
        coverage_achieved=100.0,
    )

    result = run_pipeline(
        target_node_id="sample::calculate_discount",
        strategy="unit",
        bundle=bundle,
        max_retries=3,
        planner_cls=mock_planner,
        writer_cls=mock_writer,
        validator_cls=mock_validator,
    )

    assert result["status"] == "accepted"
    assert result["total_attempts"] == 2
    assert result["internal_retries"] == 1
    assert result["external_retries"] == 0

    # Verify Planner was called twice: once initially, then again with feedback!
    assert mock_planner.generate_plan.call_count == 2
    second_planner_call_kwargs = mock_planner.generate_plan.call_args_list[1].kwargs
    assert "assert True" in second_planner_call_kwargs["feedback"]


def test_orchestrator_external_loopback_to_writer() -> None:
    """
    Verifies that an external validation failure (sandbox error) increments the
    retry counter and loops back to the Writer mock with stderr/traceback.
    """
    bundle = _make_dummy_bundle()
    matrix = _make_dummy_matrix()
    candidate = CandidateTest(test_code="def test_run(): pass")

    mock_planner = MagicMock()
    mock_planner.generate_plan.return_value = matrix

    mock_writer = MagicMock()
    mock_writer.synthesize.return_value = candidate

    mock_validator = MagicMock()
    mock_validator.run_internal_validation.return_value = ValidationResult(
        is_valid=True,
        failed_phase="none",
        feedback="AST clean",
    )
    # External validator fails on run 1, passes on run 2
    mock_validator.run_external_validation.side_effect = [
        ValidationResult(
            is_valid=False,
            failed_phase="external",
            feedback="ModuleNotFoundError: No module named 'fake_module'",
            exit_code=1,
            stderr="Traceback: fake_module not found",
        ),
        ValidationResult(
            is_valid=True,
            failed_phase="none",
            feedback="Sandbox passed.",
            coverage_achieved=100.0,
        ),
    ]

    result = run_pipeline(
        target_node_id="sample::calculate_discount",
        strategy="unit",
        bundle=bundle,
        max_retries=3,
        planner_cls=mock_planner,
        writer_cls=mock_writer,
        validator_cls=mock_validator,
    )

    assert result["status"] == "accepted"
    assert result["total_attempts"] == 2
    assert result["internal_retries"] == 0
    assert result["external_retries"] == 1

    # Planner was called once initially
    assert mock_planner.generate_plan.call_count == 1
    # Writer was called twice: second time with external feedback
    assert mock_writer.synthesize.call_count == 2
    second_writer_kwargs = mock_writer.synthesize.call_args_list[1].kwargs
    assert "fake_module" in second_writer_kwargs["feedback"]


def test_orchestrator_max_retries_exhausted() -> None:
    """Verifies that when validation continues to fail, the orchestrator terminates after max_retries."""
    bundle = _make_dummy_bundle()
    matrix = _make_dummy_matrix()
    candidate = CandidateTest(test_code="def test_forever_bad(): assert True")

    mock_planner = MagicMock()
    mock_planner.generate_plan.return_value = matrix

    mock_writer = MagicMock()
    mock_writer.synthesize.return_value = candidate

    mock_validator = MagicMock()
    # Continual internal failure
    mock_validator.run_internal_validation.return_value = ValidationResult(
        is_valid=False,
        failed_phase="internal",
        feedback="Tautological assertion: assert True",
    )

    result = run_pipeline(
        target_node_id="sample::calculate_discount",
        strategy="unit",
        bundle=bundle,
        max_retries=2,
        planner_cls=mock_planner,
        writer_cls=mock_writer,
        validator_cls=mock_validator,
    )

    assert result["status"] == "rejected"
    assert result["total_attempts"] == 2
    assert result["internal_retries"] == 2
    assert result["validation"].failed_phase == "internal"
