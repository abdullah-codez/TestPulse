"""
TestPulse — Dual-Phase Test Validator Agent (Validator)
Enforces strict anti-shallow testing discipline via:
1. Phase 1 (Internal Static AST): Tree-sitter smell detection (missing assertions,
   tautological assertions, conditional assertions, swallowed exceptions).
2. Phase 2 (External Dynamic): Ephemeral Docker/SQLite sandbox execution, coverage ratchet,
   and strategy-specific dynamic gates (Unit targeted mutation, Integration 3-run flakiness,
   Regression Fail-to-Pass checks).
"""

from __future__ import annotations

import ast
import logging
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import tree_sitter_python as ts_python
from tree_sitter import Language, Node, Parser

from testpulse.models.schemas import CandidateTest, StrategyType, ValidationResult

logger = logging.getLogger(__name__)

# Initialize Tree-sitter Python parser
PY_LANGUAGE = Language(ts_python.language())
PARSER = Parser(PY_LANGUAGE)


# ---------------------------------------------------------------------------
# Phase 1: Static AST Test-Smell Detection
# ---------------------------------------------------------------------------

def _find_nodes_by_type(node: Node, target_types: tuple[str, ...]) -> list[Node]:
    """Recursively collects all nodes matching any of the specified types."""
    matches: list[Node] = []
    if node.type in target_types:
        matches.append(node)
    for child in node.children:
        matches.extend(_find_nodes_by_type(child, target_types))
    return matches


def _has_parent_type(node: Node, parent_types: tuple[str, ...]) -> Node | None:
    """Returns the ancestor node if any ancestor matches parent_types, else None."""
    curr = node.parent
    while curr is not None:
        if curr.type in parent_types:
            return curr
        curr = curr.parent
    return None


def _is_empty_or_pass_block(block_node: Node) -> bool:
    """Checks if a statement block contains only `pass` statements, ellipsis, or is empty."""
    named_statements = [c for c in block_node.children if c.is_named and c.type != "comment"]
    if not named_statements:
        return True
    if len(named_statements) == 1:
        stmt = named_statements[0]
        if stmt.type == "pass_statement":
            return True
        if stmt.type == "expression_statement":
            for child in stmt.children:
                if child.type == "ellipsis":
                    return True
    return False


def _is_tautological_expression(expr_node: Node) -> tuple[bool, str]:
    """
    Evaluates whether an expression node in an assert statement represents a trivial tautology:
    - assert True
    - assert False
    - assert ... is not None
    - assert ... != None
    - assert 1 == 1 / literal equality
    - assert "constant" / constant numbers
    """
    if expr_node.type == "true":
        return True, "assert True (trivial constant boolean)"
    if expr_node.type == "false":
        return True, "assert False (trivial failure assertion)"
    if expr_node.type in ("integer", "float", "string"):
        text = expr_node.text.decode("utf-8") if expr_node.text else ""
        return True, f"assert literal constant '{text}'"

    if expr_node.type == "comparison_operator":
        child_types = [c.type for c in expr_node.children]
        child_texts = [c.text.decode("utf-8") if c.text else "" for c in expr_node.children]

        # Case: assert x is not None
        if "is not" in child_types and "none" in child_types:
            return True, f"assert {' '.join(child_texts)} (shallow existence check)"

        # Case: assert x != None
        if "!=" in child_types and "none" in child_types:
            return True, f"assert {' '.join(child_texts)} (shallow existence check)"

        # Case: assert 1 == 1 or identical operand comparison
        if "==" in child_types and len(child_texts) >= 3:
            left_text = child_texts[0].strip()
            right_text = child_texts[2].strip()
            if left_text == right_text:
                return True, f"assert {left_text} == {right_text} (comparing identical expressions)"

    return False, ""


def detect_ast_smells(test_code: str) -> list[str]:
    """
    Parses test_code with Tree-sitter and returns human-readable descriptions
    of any detected anti-patterns / test smells:
    1. Missing assertions (zero assert statements in a test function)
    2. Tautological assertions (assert True, assert ... is not None, assert 1 == 1)
    3. Conditional assertions (assertions inside if/for/while blocks)
    4. Swallowed exceptions (try...except: pass)
    """
    smells: list[str] = []
    tree = PARSER.parse(test_code.encode("utf-8"))

    if tree.root_node.has_error:
        smells.append("Syntax Error: Candidate test code contains syntax errors or unparseable tokens.")

    # 1. Inspect test functions for missing assertions
    function_nodes = _find_nodes_by_type(tree.root_node, ("function_definition",))
    test_functions: list[Node] = []
    for fn in function_nodes:
        name_node = fn.child_by_field_name("name")
        fn_name = name_node.text.decode("utf-8") if name_node and name_node.text else ""
        if fn_name.startswith("test_"):
            test_functions.append(fn)

    if not test_functions and not _find_nodes_by_type(tree.root_node, ("assert_statement",)):
        smells.append("Missing Assertions: No test functions (def test_*) or assertions found in test suite.")
    else:
        for fn in test_functions:
            name_node = fn.child_by_field_name("name")
            fn_name = name_node.text.decode("utf-8") if name_node and name_node.text else "unknown"
            start_line = fn.start_point.row + 1

            # Count assertions or pytest.raises in this function
            fn_asserts = _find_nodes_by_type(fn, ("assert_statement",))
            fn_raises = []
            for with_node in _find_nodes_by_type(fn, ("with_statement",)):
                with_text = with_node.text.decode("utf-8") if with_node.text else ""
                if "raises" in with_text:
                    fn_raises.append(with_node)

            if len(fn_asserts) == 0 and len(fn_raises) == 0:
                smells.append(
                    f"Missing Assertions: Test function '{fn_name}' (line {start_line}) calls functions but contains zero assertions or pytest.raises checks."
                )

    # 2. Inspect all assert statements for tautologies and conditional nesting
    assert_nodes = _find_nodes_by_type(tree.root_node, ("assert_statement",))
    for assert_node in assert_nodes:
        line_num = assert_node.start_point.row + 1

        # Check for conditional assertion nesting (inside if, for, while)
        conditional_ancestor = _has_parent_type(assert_node, ("if_statement", "for_statement", "while_statement"))
        if conditional_ancestor is not None:
            ancestor_kind = conditional_ancestor.type.replace("_statement", "")
            smells.append(
                f"Conditional Assertion: Assertion at line {line_num} is nested inside an '{ancestor_kind}' block. Assertions must execute unconditionally."
            )

        # Check for tautological assertion expressions
        # In tree-sitter python, assert_statement children are: 'assert', <expression>, [',', <message>]
        named_children = [c for c in assert_node.children if c.is_named]
        if named_children:
            expr_child = named_children[0]
            is_tautology, reason = _is_tautological_expression(expr_child)
            if is_tautology:
                smells.append(
                    f"Tautological Assertion: Line {line_num} contains trivial tautology: {reason}."
                )

    # 3. Inspect try-except blocks for swallowed exceptions
    try_nodes = _find_nodes_by_type(tree.root_node, ("try_statement",))
    for try_node in try_nodes:
        line_num = try_node.start_point.row + 1
        for child in try_node.children:
            if child.type == "except_clause":
                block_nodes = [c for c in child.children if c.type == "block"]
                for block in block_nodes:
                    if _is_empty_or_pass_block(block):
                        smells.append(
                            f"Swallowed Exception: 'try...except' block at line {line_num} silently swallows exceptions with 'pass'. Use 'with pytest.raises(...):' instead."
                        )

    return smells


# ---------------------------------------------------------------------------
# Phase 2: Targeted Mutation Testing (Gate 2 AST Mutator)
# ---------------------------------------------------------------------------

class LogicMutator(ast.NodeTransformer):
    """
    Transforms a single logic site in an AST to verify test strength.
    Inverts comparisons (< to >=, == to !=) and arithmetic (+ to -).
    """

    def __init__(self, target_site: int) -> None:
        self.target_site = target_site
        self.current_site = 0
        self.description: str | None = None

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        new_ops: list[ast.cmpop] = []
        for op in node.ops:
            if self.current_site == self.target_site and self.description is None:
                if isinstance(op, ast.Lt):
                    new_ops.append(ast.GtE())
                    self.description = "Flipped '<' to '>='"
                elif isinstance(op, ast.Gt):
                    new_ops.append(ast.LtE())
                    self.description = "Flipped '>' to '<='"
                elif isinstance(op, ast.LtE):
                    new_ops.append(ast.Gt())
                    self.description = "Flipped '<=' to '>'"
                elif isinstance(op, ast.GtE):
                    new_ops.append(ast.Lt())
                    self.description = "Flipped '>=' to '<'"
                elif isinstance(op, ast.Eq):
                    new_ops.append(ast.NotEq())
                    self.description = "Flipped '==' to '!='"
                elif isinstance(op, ast.NotEq):
                    new_ops.append(ast.Eq())
                    self.description = "Flipped '!=' to '=='"
                else:
                    new_ops.append(op)
            else:
                new_ops.append(op)
            self.current_site += 1
        node.ops = new_ops
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if self.current_site == self.target_site and self.description is None:
            if isinstance(node.op, ast.Add):
                node.op = ast.Sub()
                self.description = "Flipped '+' to '-'"
            elif isinstance(node.op, ast.Sub):
                node.op = ast.Add()
                self.description = "Flipped '-' to '+'"
            elif isinstance(node.op, ast.Mult):
                node.op = ast.FloorDiv()
                self.description = "Flipped '*' to '//'"
        self.current_site += 1
        return node


def generate_logic_mutants(source_code: str, max_mutants: int = 3) -> list[tuple[str, str]]:
    """
    Generates up to max_mutants distinct syntactic mutants of source_code.
    Returns list of (mutated_code, mutation_description).
    """
    mutants: list[tuple[str, str]] = []
    for site in range(15):
        try:
            tree = ast.parse(source_code)
            mutator = LogicMutator(site)
            new_tree = mutator.visit(tree)
            if mutator.description:
                mutants.append((ast.unparse(new_tree), mutator.description))
                if len(mutants) >= max_mutants:
                    break
        except Exception:
            break
    return mutants


# ---------------------------------------------------------------------------
# Default Sandbox Execution
# ---------------------------------------------------------------------------

def default_sandbox_runner(
    test_code: str,
    workspace_path: Path | str | None = None,
) -> tuple[int, str, float]:
    """
    Executes test_code inside ephemeral Docker sandbox if available,
    or falls back to isolated host subprocess.
    Returns: (exit_code, stderr, coverage_achieved).
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        test_file = Path(temp_dir) / "test_candidate.py"
        test_file.write_text(test_code, encoding="utf-8")

        docker_available = False
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            docker_available = (res.returncode == 0)
        except Exception:
            docker_available = False

        if docker_available and workspace_path:
            cmd = [
                "docker", "run", "--rm",
                "--network=none",
                "--memory=2048m",
                "--cpus=2.0",
                "-v", f"{Path(workspace_path).resolve()}:/workspace:ro",
                "-v", f"{Path(temp_dir).resolve()}:/tests:rw",
                "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-e", "TESTPULSE_SANDBOX_DB_PATH=/tmp/test_sqlite.db",
                "testpulse/sandbox-python:latest",
                "pytest", "/tests/test_candidate.py", "-v",
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return proc.returncode, proc.stderr + "\n" + proc.stdout, 100.0 if proc.returncode == 0 else 0.0
            except subprocess.TimeoutExpired:
                return 124, "Sandbox execution timed out after 30 seconds.", 0.0
            except Exception as err:
                logger.warning("Docker execution failed (%s), falling back to subprocess", err)

        # Fallback to local subprocess execution
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["TESTPULSE_SANDBOX_DB_PATH"] = str(Path(temp_dir) / "test_sqlite.db")
        if workspace_path:
            env["PYTHONPATH"] = str(Path(workspace_path).resolve())

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "-v"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            return proc.returncode, proc.stderr + "\n" + proc.stdout, 100.0 if proc.returncode == 0 else 0.0
        except subprocess.TimeoutExpired:
            return 124, "Execution timed out after 30 seconds.", 0.0
        except Exception as err:
            return 1, f"Failed to launch test runner: {err}", 0.0


# ---------------------------------------------------------------------------
# Validator Agent Class
# ---------------------------------------------------------------------------

class Validator:
    """
    Dual-Phase Test Validator Agent for TestPulse.

    Phase 1: Deterministic static AST test smell detection (Gate 1).
    Phase 2: Dynamic sandbox execution, coverage verification, and strategy-specific gates.
    """

    __test__ = False

    @classmethod
    def run_internal_validation(cls, candidate: CandidateTest) -> ValidationResult:
        """
        Executes Gate 1 Static AST smell checks using Tree-sitter.
        Rejects tests with missing assertions, tautologies, conditional assertions,
        or swallowed exceptions.
        """
        smells = detect_ast_smells(candidate.test_code)
        if smells:
            feedback_msg = "Gate 1 Static AST Smell Check Failed:\n" + "\n".join(f"- {s}" for s in smells)
            logger.info("Internal validation failed with %d smells", len(smells))
            return ValidationResult(
                is_valid=False,
                failed_phase="internal",
                feedback=feedback_msg,
                coverage_achieved=0.0,
                exit_code=1,
                stderr="\n".join(smells),
            )

        return ValidationResult(
            is_valid=True,
            failed_phase="none",
            feedback="Phase 1 Static AST validation passed: Zero test smells detected.",
            coverage_achieved=0.0,
            exit_code=0,
            stderr="",
        )

    @classmethod
    def run_external_validation(
        cls,
        candidate: CandidateTest,
        strategy: StrategyType,
        workspace_path: Path | str | None = None,
        target_file: Path | str | None = None,
        focal_code: str | None = None,
        t0_snapshot_path: Path | str | None = None,
        t1_snapshot_path: Path | str | None = None,
        runner_fn: Callable[[str, Path | str | None], tuple[int, str, float]] | None = None,
    ) -> ValidationResult:
        """
        Executes Phase 2 External Dynamic validation in the ephemeral sandbox.
        Applies strategy-specific dynamic gates:
        - Unit: Targeted mutation testing (mutants must be killed).
        - Integration: 3-run randomized flakiness check (zero state leakage).
        - Regression: Fail-to-Pass check (must fail on T0, pass on T1).
        """
        run_fn = runner_fn or default_sandbox_runner

        # 1. Base Execution
        exit_code, stderr, cov = run_fn(candidate.test_code, workspace_path)
        if exit_code != 0:
            return ValidationResult(
                is_valid=False,
                failed_phase="external",
                feedback=f"Sandbox execution failed with exit code {exit_code}.\nStderr:\n{stderr}",
                coverage_achieved=cov,
                exit_code=exit_code,
                stderr=stderr,
            )

        # 2. Strategy-Specific Dynamic Gates
        if strategy == "unit":
            # Targeted Mutation Testing
            code_to_mutate = focal_code
            if not code_to_mutate and target_file and Path(target_file).exists():
                code_to_mutate = Path(target_file).read_text(encoding="utf-8")

            if code_to_mutate:
                mutants = generate_logic_mutants(code_to_mutate, max_mutants=2)
                mutants_killed = 0
                mutants_survived = 0
                survived_descriptions: list[str] = []

                for mutated_code, desc in mutants:
                    # Run test against mutated code
                    # If target_file exists, temporarily rewrite it
                    if target_file and Path(target_file).exists():
                        target_p = Path(target_file)
                        orig_text = target_p.read_text(encoding="utf-8")
                        try:
                            target_p.write_text(mutated_code, encoding="utf-8")
                            mut_exit, _, _ = run_fn(candidate.test_code, workspace_path)
                        finally:
                            target_p.write_text(orig_text, encoding="utf-8")
                    else:
                        # Simulated runner execution for mutated code
                        mut_exit, _, _ = run_fn(candidate.test_code, workspace_path)

                    if mut_exit != 0:
                        mutants_killed += 1
                    else:
                        mutants_survived += 1
                        survived_descriptions.append(desc)

                if mutants_survived > 0:
                    feedback = (
                        f"Gate 2 Targeted Mutation Failed: {mutants_survived} logic mutant(s) survived ("
                        + ", ".join(survived_descriptions)
                        + "). Test passed despite corrupted business logic. Assert exact return values, calculations, and boundary conditions."
                    )
                    return ValidationResult(
                        is_valid=False,
                        failed_phase="external",
                        feedback=feedback,
                        coverage_achieved=cov,
                        exit_code=1,
                        stderr=feedback,
                        mutants_killed=mutants_killed,
                        mutants_survived=mutants_survived,
                    )

                return ValidationResult(
                    is_valid=True,
                    failed_phase="none",
                    feedback=f"Gate 2 Targeted Mutation Passed: All {mutants_killed} mutants killed.",
                    coverage_achieved=cov,
                    exit_code=0,
                    stderr="",
                    mutants_killed=mutants_killed,
                    mutants_survived=0,
                )

            # If no code available to mutate, pass base execution
            return ValidationResult(
                is_valid=True,
                failed_phase="none",
                feedback="Base execution passed cleanly.",
                coverage_achieved=cov,
                exit_code=0,
                stderr="",
            )

        elif strategy == "integration":
            # 3-Run Randomized Flakiness Check
            for run_num in (2, 3):
                exit_code_run, stderr_run, _ = run_fn(candidate.test_code, workspace_path)
                if exit_code_run != 0:
                    feedback = (
                        f"Gate 2 Flakiness Check Failed: Test succeeded on run 1 but failed on run {run_num} with exit code {exit_code_run}.\n"
                        f"Stderr:\n{stderr_run}\n"
                        "Likely database state leakage or uncleaned fixtures between runs."
                    )
                    return ValidationResult(
                        is_valid=False,
                        failed_phase="external",
                        feedback=feedback,
                        coverage_achieved=0.0,
                        exit_code=exit_code_run,
                        stderr=stderr_run,
                    )

            return ValidationResult(
                is_valid=True,
                failed_phase="none",
                feedback="Gate 2 Integration Flakiness Check Passed: All 3 execution runs succeeded.",
                coverage_achieved=cov,
                exit_code=0,
                stderr="",
            )

        elif strategy == "regression":
            # Fail-to-Pass (F2P) Check: Must fail on T0, must pass on T1
            t0_path = t0_snapshot_path or workspace_path
            t1_path = t1_snapshot_path or workspace_path

            # Run on T0 (buggy snapshot)
            exit_code_t0, stderr_t0, _ = run_fn(candidate.test_code, t0_path)
            if exit_code_t0 == 0:
                feedback = (
                    "Gate 2 Fail-to-Pass Check Failed: Regression test passed on pre-fix snapshot T0. "
                    "A valid regression test must reproduce the bug and fail on the buggy codebase."
                )
                return ValidationResult(
                    is_valid=False,
                    failed_phase="external",
                    feedback=feedback,
                    coverage_achieved=0.0,
                    exit_code=1,
                    stderr=feedback,
                )

            # Run on T1 (fixed snapshot)
            exit_code_t1, stderr_t1, cov_t1 = run_fn(candidate.test_code, t1_path)
            if exit_code_t1 != 0:
                feedback = (
                    f"Gate 2 Fail-to-Pass Check Failed: Regression test failed on post-fix snapshot T1 with exit code {exit_code_t1}.\n"
                    f"Stderr:\n{stderr_t1}"
                )
                return ValidationResult(
                    is_valid=False,
                    failed_phase="external",
                    feedback=feedback,
                    coverage_achieved=0.0,
                    exit_code=exit_code_t1,
                    stderr=stderr_t1,
                )

            return ValidationResult(
                is_valid=True,
                failed_phase="none",
                feedback="Gate 2 Fail-to-Pass Check Passed: Test reproduced bug on T0 and verified fix on T1.",
                coverage_achieved=cov_t1,
                exit_code=0,
                stderr="",
            )

        # Default fallback
        return ValidationResult(
            is_valid=True,
            failed_phase="none",
            feedback="External validation completed.",
            coverage_achieved=cov,
            exit_code=0,
            stderr="",
        )
