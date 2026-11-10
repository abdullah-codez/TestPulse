"""
TestPulse — Test Planning Agent (Planner)
Synthesizes exhaustive, strategy-aware BehaviorMatrix test plans via Tier-1 LLM Router.
Enforces anti-shallow validation rules and strict mock boundaries.
"""

from __future__ import annotations

from testpulse.llm.router import LLMRouter
from testpulse.models.schemas import BehaviorMatrix, ContextBundle, StrategyType


def build_system_prompt(strategy: StrategyType) -> str:
    """Builds a strategy-aware system prompt for the QA Architect LLM."""
    base = (
        "You are the TestPulse QA Architect, an autonomous agent responsible for synthesizing "
        "exhaustive, anti-shallow test behavior matrices for backend Python/FastAPI systems.\n\n"
        "Your objective: Synthesize a high-precision BehaviorMatrix in valid JSON format.\n\n"
        "MANDATORY ANTI-SHALLOW QUALITY RULES:\n"
        "1. No trivial tautologies (e.g. `assert x is not None`, `assert True`). Every case must assert concrete values, status codes, or raised exceptions.\n"
        "2. Strict mock boundary compliance: Never mock the target symbol or forbidden components specified in mock_policy.\n"
    )

    if strategy == "unit":
        strategy_rules = (
            "STRATEGY: UNIT TESTING\n"
            "- Demand branch coverage across every conditional branch, loop, and path in focal_code.\n"
            "- Demand strict mathematical boundary cases (e.g. 0, negatives, off-by-one, None, empty collections, caps/limits).\n"
            "- Incorporate business rules from descriptive_context (e.g. discount caps, validation thresholds).\n"
            "- Demand negative error-raising paths asserting explicit domain exceptions or ValueError.\n"
        )
    elif strategy == "integration":
        strategy_rules = (
            "STRATEGY: INTEGRATION TESTING\n"
            "- Exercise the full route -> service -> SQLite flow using FastAPI TestClient / AsyncClient.\n"
            "- Demand HTTP status code verification (200/201 success, 404 not found, 422 unprocessable entity for schema validation).\n"
            "- Include Pydantic schema validation edge cases and boundary payloads.\n"
            "- Demand database state verification (verifying database rows are created, updated, or unaffected).\n"
        )
    else:  # regression
        strategy_rules = (
            "STRATEGY: REGRESSION TESTING\n"
            "- Demand a mandatory Fail-to-Pass (F2P) reproducer case reproducing the exact modified logic defect.\n"
            "- The reproducer must be formulated to fail on the pre-fix code and pass on the post-fix code.\n"
            "- Include caller contract preservation cases ensuring upstream callers and downstream dependents remain functional.\n"
        )

    json_format = (
        "\nOUTPUT FORMAT:\n"
        "Return ONLY a single valid JSON object strictly matching this schema:\n"
        "{\n"
        f'  "strategy": "{strategy}",\n'
        '  "target_node_id": "<string>",\n'
        '  "target_symbol": "<string>",\n'
        '  "cases": [\n'
        '    {\n'
        '      "id": "CASE-1",\n'
        '      "category": "happy" | "boundary" | "negative",\n'
        '      "description": "<detailed test scenario>",\n'
        '      "inputs": { ... } | "<input description>",\n'
        '      "expected_outcome": "<concrete expected return value, status code, or exception>"\n'
        '    }\n'
        '  ],\n'
        '  "mock_constraints": ["<constraint 1>", "<constraint 2>"],\n'
        '  "uncovered_lines": []\n'
        "}\n"
    )

    return base + "\n" + strategy_rules + json_format


def build_user_prompt(bundle: ContextBundle, feedback: str | None = None) -> str:
    """Formats the ContextBundle into an explicit planning prompt."""
    deps = "\n\n".join(bundle.dependency_code) if bundle.dependency_code else "None"
    desc = "\n\n".join(bundle.descriptive_context) if bundle.descriptive_context else "None"
    mock_rules = "\n".join(f"- {k}: {v}" for k, v in bundle.mock_policy.items())
    fixtures = ", ".join(bundle.existing_fixtures) if bundle.existing_fixtures else "None"

    prompt = (
        f"TARGET: {bundle.target_symbol} ({bundle.strategy.upper()})\n"
        f"Node ID: {bundle.target_node_id}\n"
        f"Source File: {bundle.source_file} (Lines: {bundle.line_span[0]}-{bundle.line_span[1]})\n"
        f"Cyclomatic Complexity: {bundle.cyclomatic_complexity}\n\n"
        f"=== FOCAL CODE UNDER TEST ===\n{bundle.focal_code}\n\n"
        f"=== DEPENDENCY CODE (Pipeline A) ===\n{deps}\n\n"
        f"=== DESCRIPTIVE CONTEXT & BUSINESS RULES (Pipeline B) ===\n{desc}\n\n"
        f"=== MOCK POLICY ===\n{mock_rules}\n\n"
        f"=== EXISTING FIXTURES ===\n{fixtures}\n\n"
    )

    if feedback:
        prompt += (
            f"=== PREVIOUS ATTEMPT REJECTED FOR SHALLOW VALIDATION ===\n"
            f"{feedback}\n\n"
            f"Address the smell above: generate a more rigorous BehaviorMatrix with concrete boundary assertions.\n"
        )
    else:
        prompt += f"Synthesize the BehaviorMatrix test plan for {bundle.target_symbol} following all {bundle.strategy.upper()} requirements."

    return prompt


class TestPlanner:
    """
    Test Planning Agent for TestPulse.

    Consumes a ContextBundle and orchestrates the Tier-1 LLM Router
    to produce a verified, anti-shallow BehaviorMatrix.
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
    def generate_plan(
        cls,
        bundle: ContextBundle,
        feedback: str | None = None,
        router: LLMRouter | None = None,
        models: list[str] | None = None,
    ) -> BehaviorMatrix:
        """Generates a structured BehaviorMatrix from a ContextBundle."""
        active_router = router or LLMRouter()
        system_prompt = build_system_prompt(bundle.strategy)
        user_prompt = build_user_prompt(bundle, feedback=feedback)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        matrix = active_router.complete_structured(
            messages=messages,
            schema=BehaviorMatrix,
            models=models,
        )

        # Enforce bundle metadata alignment
        matrix.strategy = bundle.strategy
        if not matrix.target_node_id:
            matrix.target_node_id = bundle.target_node_id
        if not matrix.target_symbol:
            matrix.target_symbol = bundle.target_symbol

        return matrix



