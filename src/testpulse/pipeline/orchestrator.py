"""
TestPulse — Pipeline Orchestrator (Component 1)
Connects the 4-agent sequential pipeline:
  ContextGatherer -> TestPlanner -> TestWriter -> Validator

Handles internal and external feedback loops with strict retry budgeting:
- Internal Loop-Back: When Validator Phase 1 rejects shallow AST smells,
  loops back to Planner with AST smell feedback to regenerate a rigorous BehaviorMatrix.
- External Loop-Back: When Validator Phase 2 rejects execution/mutation errors,
  loops back to Writer with execution stderr/traceback to fix test implementation.
- Max Retries: 3 attempts per target.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import networkx as nx

from testpulse.llm.router import LLMRouter
from testpulse.models.schemas import (
    BehaviorMatrix,
    CandidateTest,
    ContextBundle,
    StrategyType,
    ValidationResult,
)
from testpulse.pipeline.context_gatherer import ContextGatherer
from testpulse.pipeline.planner import TestPlanner
from testpulse.pipeline.validator import Validator
from testpulse.pipeline.writer import TestWriter

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    State machine orchestrator managing sequential execution across
    ContextGatherer, TestPlanner, TestWriter, and Validator.
    """

    def __init__(
        self,
        router: LLMRouter | None = None,
        models: list[str] | None = None,
        max_retries: int = 3,
    ) -> None:
        self.router = router or LLMRouter()
        self.models = models
        self.max_retries = max_retries

    def run(
        self,
        target_node_id: str,
        strategy: StrategyType,
        G: nx.DiGraph | None = None,
        bundle: ContextBundle | None = None,
        workspace_path: Path | str | None = None,
        target_file: Path | str | None = None,
        focal_code: str | None = None,
        t0_snapshot_path: Path | str | None = None,
        t1_snapshot_path: Path | str | None = None,
        embedder_fn: Callable[[str], list[float]] | None = None,
        runner_fn: Callable[[str, Path | str | None], tuple[int, str, float]] | None = None,
        planner_cls: Any = None,
        writer_cls: Any = None,
        validator_cls: Any = None,
    ) -> dict[str, Any]:
        """
        Executes the sequential 4-agent verification pipeline for a single target.
        Enforces sequential target execution and bounded repair loops.
        """
        planner = planner_cls or TestPlanner
        writer = writer_cls or TestWriter
        validator = validator_cls or Validator

        # 1. Gather Context
        active_bundle: ContextBundle
        if bundle is None:
            if G is None:
                raise ValueError("Either 'bundle' or 'G' (nx.DiGraph) must be provided to run_pipeline.")
            active_bundle = ContextGatherer.build_bundle(
                G=G,
                target_node_id=target_node_id,
                strategy=strategy,
                workspace_path=workspace_path,
                embedder_fn=embedder_fn,
            )
        else:
            active_bundle = bundle

        resolved_target_file = target_file
        if resolved_target_file is None and workspace_path and active_bundle.source_file:
            candidate_p = Path(workspace_path) / active_bundle.source_file
            if candidate_p.exists():
                resolved_target_file = candidate_p

        resolved_focal_code = focal_code or active_bundle.focal_code

        # 2. Initial Plan Generation
        matrix: BehaviorMatrix = planner.generate_plan(
            bundle=active_bundle,
            feedback=None,
            router=self.router,
            models=self.models,
        )

        # 3. Validation & Feedback Loop
        attempt = 0
        internal_retries = 0
        external_retries = 0
        writer_feedback: str | None = None
        candidate: CandidateTest | None = None
        last_validation: ValidationResult | None = None

        while attempt <= self.max_retries:
            # Step A: Synthesize candidate test
            synth_res = writer.synthesize(
                bundle=active_bundle,
                matrix=matrix,
                feedback=writer_feedback,
                router=self.router,
                models=self.models,
            )
            candidate = synth_res if isinstance(synth_res, CandidateTest) else CandidateTest(test_code=str(synth_res))

            # Step B: Phase 1 Internal Validation (Static AST smells)
            val_internal = validator.run_internal_validation(candidate)
            last_validation = val_internal

            if not val_internal.is_valid:
                if attempt >= self.max_retries:
                    logger.warning(
                        "Max retries (%d) reached on internal validation failure for target %s",
                        self.max_retries,
                        target_node_id,
                    )
                    break

                # Internal Loop-Back -> Planner Agent
                attempt += 1
                internal_retries += 1
                logger.info(
                    "Internal validation failed for %s (attempt %d/%d). Regenerating plan with Planner.",
                    target_node_id,
                    attempt,
                    self.max_retries,
                )
                matrix = planner.generate_plan(
                    bundle=active_bundle,
                    feedback=val_internal.feedback,
                    router=self.router,
                    models=self.models,
                )
                writer_feedback = None  # Reset writer feedback because BehaviorMatrix changed
                continue

            # Step C: Phase 2 External Validation (Sandbox dynamic gates)
            val_external = validator.run_external_validation(
                candidate=candidate,
                strategy=strategy,
                workspace_path=workspace_path,
                target_file=resolved_target_file,
                focal_code=resolved_focal_code,
                t0_snapshot_path=t0_snapshot_path,
                t1_snapshot_path=t1_snapshot_path,
                runner_fn=runner_fn,
            )
            last_validation = val_external

            if not val_external.is_valid:
                if attempt >= self.max_retries:
                    logger.warning(
                        "Max retries (%d) reached on external validation failure for target %s",
                        self.max_retries,
                        target_node_id,
                    )
                    break

                # External Loop-Back -> Writer Agent
                attempt += 1
                external_retries += 1
                logger.info(
                    "External validation failed for %s (attempt %d/%d). Retrying code synthesis with Writer.",
                    target_node_id,
                    attempt,
                    self.max_retries,
                )
                writer_feedback = val_external.feedback
                continue

            # All gates passed successfully!
            logger.info(
                "Pipeline succeeded for target %s on attempt %d (%d internal retries, %d external retries)",
                target_node_id,
                attempt + 1,
                internal_retries,
                external_retries,
            )
            return {
                "status": "accepted",
                "target_node_id": target_node_id,
                "strategy": strategy,
                "bundle": active_bundle,
                "matrix": matrix,
                "candidate": candidate,
                "validation": val_external,
                "total_attempts": attempt + 1,
                "internal_retries": internal_retries,
                "external_retries": external_retries,
            }

        # Retries exhausted
        logger.warning(
            "Pipeline rejected test for target %s after %d attempts",
            target_node_id,
            attempt,
        )
        return {
            "status": "rejected",
            "target_node_id": target_node_id,
            "strategy": strategy,
            "bundle": active_bundle,
            "matrix": matrix,
            "candidate": candidate,
            "validation": last_validation,
            "total_attempts": attempt,
            "internal_retries": internal_retries,
            "external_retries": external_retries,
        }


def run_pipeline(
    target_node_id: str,
    strategy: StrategyType,
    G: nx.DiGraph | None = None,
    bundle: ContextBundle | None = None,
    workspace_path: Path | str | None = None,
    target_file: Path | str | None = None,
    focal_code: str | None = None,
    t0_snapshot_path: Path | str | None = None,
    t1_snapshot_path: Path | str | None = None,
    embedder_fn: Callable[[str], list[float]] | None = None,
    max_retries: int = 3,
    router: LLMRouter | None = None,
    models: list[str] | None = None,
    runner_fn: Callable[[str, Path | str | None], tuple[int, str, float]] | None = None,
    planner_cls: Any = None,
    writer_cls: Any = None,
    validator_cls: Any = None,
) -> dict[str, Any]:
    """
    Convenience function to execute the TestPulse pipeline for a given target.
    """
    orchestrator = PipelineOrchestrator(
        router=router,
        models=models,
        max_retries=max_retries,
    )
    return orchestrator.run(
        target_node_id=target_node_id,
        strategy=strategy,
        G=G,
        bundle=bundle,
        workspace_path=workspace_path,
        target_file=target_file,
        focal_code=focal_code,
        t0_snapshot_path=t0_snapshot_path,
        t1_snapshot_path=t1_snapshot_path,
        embedder_fn=embedder_fn,
        runner_fn=runner_fn,
        planner_cls=planner_cls,
        writer_cls=writer_cls,
        validator_cls=validator_cls,
    )
