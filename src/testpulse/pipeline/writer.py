"""
TestPulse — Test Writer Agent (Writer)
Synthesizes clean, PEP-8 compliant pytest test suites based on a BehaviorMatrix
and ContextBundle. Enforces strategy-specific mocking and execution boundaries.
"""

from __future__ import annotations

import ast
import json
import logging
import re

from testpulse.llm.router import LLMRouter
from testpulse.models.schemas import BehaviorMatrix, CandidateTest, ContextBundle

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the TestPulse Test Writer, an autonomous expert QA engineer synthesizing executable, anti-shallow pytest test suites for Python/FastAPI applications.

Your task: Implement a complete, executable pytest test file verifying the exact scenarios specified in the provided BehaviorMatrix.

CRITICAL CODE QUALITY & STRATEGY RULES:
1. Synthesize runnable Python code with all necessary imports (pytest, unittest.mock, httpx, etc.).
2. Anti-Shallow Test Discipline:
   - Every test function MUST contain real, verifiable `assert` statements.
   - NEVER use trivial tautologies (e.g. `assert True`, `assert result is not None`, `assert 1 == 1`).
   - NEVER wrap assertions inside `if` statements or loops.
   - NEVER swallow exceptions (`try ... except: pass`). If testing exception paths, use `with pytest.raises(ExpectedException):`.
3. Strategy Constraints:
   - UNIT Strategy:
     * Exercise the target symbol directly.
     * NEVER mock the target function/method or its core business logic.
     * Use `unittest.mock.patch` exclusively for external I/O (database, external HTTP calls, filesystem).
   - INTEGRATION Strategy:
     * Use FastAPI TestClient (or `httpx.AsyncClient` with `pytest.mark.asyncio`).
     * Do NOT mock the database or internal service providers; exercise real database state and transactions.
     * Only external 3rd-party APIs may be mocked.
   - REGRESSION Strategy:
     * Focus strictly on the blast radius boundaries and defect reproduction.
     * Implement the mandatory Fail-to-Pass reproducer case.
4. Output Format:
   - Output ONLY the complete Python code file. Wrap the code in ```python ... ``` markdown code fences.
"""


def extract_python_code(content: str) -> str:
    """Strips markdown code fences (```python ... ```) or returns raw code content."""
    raw = content.strip()
    match = re.search(r"```(?:python|py)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return raw


def extract_fixtures_needed(test_code: str) -> list[str]:
    """Inspects AST of generated test code to detect fixture names used as parameters."""
    fixtures: list[str] = []
    try:
        tree = ast.parse(test_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                for arg in node.args.args:
                    arg_name = arg.arg
                    if arg_name not in ("self", "cls"):
                        fixtures.append(arg_name)
    except SyntaxError:
        pass
    return sorted(set(fixtures))


def build_writer_user_prompt(
    bundle: ContextBundle,
    matrix: BehaviorMatrix,
    feedback: str | None = None,
) -> str:
    """Formats the BehaviorMatrix and ContextBundle into an explicit code synthesis prompt."""
    cases_dict = [c.model_dump() for c in matrix.cases]
    cases_text = json.dumps(cases_dict, indent=2)
    mock_rules = "\n".join(f"- {k}: {v}" for k, v in bundle.mock_policy.items())
    fixtures = ", ".join(bundle.existing_fixtures) if bundle.existing_fixtures else "None"
    constraints = "\n".join(f"- {c}" for c in matrix.mock_constraints) if matrix.mock_constraints else "None"

    prompt = (
        f"Target Strategy: {bundle.strategy.upper()}\n"
        f"Target Symbol: {bundle.target_symbol}\n"
        f"Source File: {bundle.source_file} (Lines: {bundle.line_span[0]}-{bundle.line_span[1]})\n\n"
        f"=== FOCAL CODE UNDER TEST ===\n{bundle.focal_code}\n\n"
        f"=== BEHAVIOR MATRIX CASES TO IMPLEMENT ===\n{cases_text}\n\n"
        f"=== MOCK POLICY ===\n{mock_rules}\n\n"
        f"=== MOCK CONSTRAINTS ===\n{constraints}\n\n"
        f"=== EXISTING FIXTURES ===\n{fixtures}\n\n"
    )

    if feedback:
        prompt += (
            f"=== PREVIOUS ATTEMPT EXECUTION ERROR / FEEDBACK (FIX THESE ISSUES) ===\n"
            f"{feedback}\n\n"
            f"Please address the feedback above and produce corrected, robust pytest code.\n"
        )
    else:
        prompt += f"Synthesize the complete, executable pytest suite for {bundle.target_symbol} now."

    return prompt


class TestWriter:
    """
    Test Writer Agent for TestPulse.

    Consumes a ContextBundle and BehaviorMatrix, orchestrating the Tier-1 LLM
    to generate runnable, anti-shallow pytest test suites.
    """

    __test__ = False

    def __init__(
        self,
        router: LLMRouter | None = None,
        models: list[str] | None = None,
    ) -> None:
        self.router = router or LLMRouter()
        self.models = models

    @classmethod
    def synthesize(
        cls,
        bundle: ContextBundle,
        matrix: BehaviorMatrix,
        feedback: str | None = None,
        router: LLMRouter | None = None,
        models: list[str] | None = None,
    ) -> CandidateTest:
        """Synthesizes CandidateTest containing executable pytest code."""
        active_router = router or LLMRouter()
        user_prompt = build_writer_user_prompt(bundle, matrix, feedback=feedback)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = active_router.complete(
            messages=messages,
            models=models,
        )

        content: str = ""
        try:
            choices = getattr(response, "choices", [])
            if choices:
                content = getattr(choices[0].message, "content", "") or ""
            elif isinstance(response, dict) and "choices" in response:
                content = response["choices"][0]["message"]["content"]
        except (IndexError, KeyError, AttributeError) as err:
            raise ValueError(f"Unexpected response from LLM completion: {response}") from err

        code = extract_python_code(content)
        fixtures = extract_fixtures_needed(code)

        target_slug = re.sub(r"[^a-zA-Z0-9_]+", "_", bundle.target_symbol).strip("_")
        test_filename = f"test_{bundle.strategy}_{target_slug}.py"

        return CandidateTest(
            test_code=code,
            fixtures_needed=fixtures,
            test_file_name=test_filename,
        )
