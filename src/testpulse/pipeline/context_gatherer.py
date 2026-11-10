"""
TestPulse — Multi-Strategy Context Gathering Agent
Assembles rich, strategy-aware ContextBundles for Planner and Writer agents.
Supports Unit (bottom-up), Integration (top-down), and Regression (blast radius) targeting.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import networkx as nx

from testpulse.core.config import settings
from testpulse.graph.queries import (
    compute_blast_radius,
    select_integration_targets,
    select_unit_targets,
)
from testpulse.models.schemas import ContextBundle, StrategyType
from testpulse.rag.retriever import _resolve_target_node_id, retrieve_context_artifacts


def find_conftest_fixtures(workspace_path: Path) -> list[str]:
    """
    Discovers pytest fixtures defined in any conftest.py inside workspace_path.
    Returns function signatures (e.g. 'db_session(engine)').
    """
    fixtures: list[str] = []
    if not workspace_path.exists():
        return fixtures

    for root, _, files in os.walk(workspace_path):
        if "conftest.py" in files:
            conftest_path = Path(root) / "conftest.py"
            try:
                tree = ast.parse(conftest_path.read_text(encoding="utf-8", errors="replace"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        is_fixture = False
                        for dec in node.decorator_list:
                            dec_name = ""
                            if isinstance(dec, ast.Name):
                                dec_name = dec.id
                            elif isinstance(dec, ast.Attribute):
                                dec_name = dec.attr
                            elif isinstance(dec, ast.Call):
                                if isinstance(dec.func, ast.Name):
                                    dec_name = dec.func.id
                                elif isinstance(dec.func, ast.Attribute):
                                    dec_name = dec.func.attr
                            if "fixture" in dec_name.lower():
                                is_fixture = True
                                break
                        if is_fixture:
                            args = [a.arg for a in node.args.args if a.arg != "self"]
                            fixtures.append(f"{node.name}({', '.join(args)})")
            except Exception:
                continue

    return sorted(set(fixtures))


def _extract_source_lines_fallback(
    file_path: Path,
    line_start: int,
    line_end: int,
) -> str:
    """Fallback reader for source lines when Qdrant does not yet contain the focal chunk."""
    if not file_path.exists():
        return ""
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start_idx = max(0, line_start - 1)
        end_idx = min(len(lines), line_end)
        return "\n".join(lines[start_idx:end_idx])
    except OSError:
        return ""


class ContextGatherer:
    """
    Multi-strategy Context Gathering Agent.

    Responsibilities:
    1. Target Queue Prioritization: select_targets() ranks targets based on strategy.
    2. Context Bundle Assembly: build_bundle() retrieves and cleanly separates focal code,
       Pipeline A dependencies, Pipeline B descriptive rules, and mock policies.
    """

    def __init__(
        self,
        workspace_path: Path | str | None = None,
        qdrant_path: Path | str | None = None,
    ) -> None:
        self.workspace_path = Path(workspace_path).resolve() if workspace_path else Path.cwd()
        self.qdrant_path = Path(qdrant_path or settings.qdrant_path)

    @staticmethod
    def select_targets(
        G: nx.DiGraph,
        strategy: StrategyType,
        modified_nodes: list[str] | None = None,
        max_targets: int = settings.max_targets,
    ) -> list[str]:
        """
        Prioritizes targets for testing based on the requested strategy:
        - unit: Non-trivial business logic ranked by complexity & centrality (bottom-up).
        - integration: FastAPI route entry points (top-down).
        - regression: Modified nodes + 2-hop callers + 1-hop dependencies (blast radius).
        """
        if strategy == "unit":
            unit_targets = select_unit_targets(G, max_targets=max_targets)
            return [t["node_id"] for t in unit_targets]

        if strategy == "integration":
            int_targets = select_integration_targets(G, max_targets=max_targets)
            return [t["node_id"] for t in int_targets]

        if strategy == "regression":
            if not modified_nodes:
                raise ValueError("modified_nodes must be provided for regression strategy")
            blast = compute_blast_radius(G, modified_nodes)
            # Prioritize modified nodes first, then remaining blast radius elements
            ordered = [n for n in modified_nodes if n in blast]
            remaining = sorted(n for n in blast if n not in set(ordered))
            targets = ordered + remaining
            return targets[:max_targets]

        raise ValueError(f"Unknown strategy: {strategy}")

    @classmethod
    def build_bundle(
        cls,
        G: nx.DiGraph,
        target_node_id: str,
        strategy: StrategyType,
        workspace_path: Path | str | None = None,
        client_path: str | Path | None = None,
        embedder_fn: Callable[[str], list[float]] | None = None,
    ) -> ContextBundle:
        """
        Assembles a strategy-aware ContextBundle for a target node.

        - hop_depth: 1 for unit, 2 for integration, 2 for regression.
        - Separates chunks cleanly into focal_code, dependency_code, and descriptive_context.
        - Formulates strategy-specific mock_policy.
        """
        inst_wpath = Path(workspace_path).resolve() if workspace_path else Path.cwd()
        inst_qpath = Path(client_path or settings.qdrant_path)

        canonical_target = _resolve_target_node_id(G, target_node_id)
        target_attrs: dict[str, Any] = G.nodes.get(canonical_target, {})

        target_symbol = str(target_attrs.get("label", canonical_target))
        source_file = str(target_attrs.get("source_file", ""))
        line_start = int(target_attrs.get("line_start", 0) or 0)
        line_end = int(target_attrs.get("line_end", 0) or 0)
        cyclomatic_complexity = int(target_attrs.get("cyclomatic_complexity", 1) or 1)

        # Strategy hop depth
        hop_depth = 1 if strategy == "unit" else 2

        # Retrieve separated context artifacts via Dual-Pipeline RAG
        artifacts = retrieve_context_artifacts(
            G=G,
            target_node_id=canonical_target,
            hop_depth=hop_depth,
            client_path=inst_qpath,
            embedder_fn=embedder_fn,
        )

        focal_code = artifacts.get("focal_chunk", "").strip()
        dependency_code = [t.strip() for t in artifacts.get("dependency_chunks", []) if t.strip()]
        descriptive_context = [t.strip() for t in artifacts.get("descriptive_chunks", []) if t.strip()]

        # Fallback for focal code if not present in Qdrant index
        if not focal_code and source_file:
            abs_file = inst_wpath / source_file if not Path(source_file).is_absolute() else Path(source_file)
            code_text = _extract_source_lines_fallback(abs_file, line_start, line_end)
            if code_text:
                header = (
                    f"# [TestPulse cAST Chunk]\n"
                    f"# Node ID: {canonical_target}\n"
                    f"# File: {source_file} (L{line_start}-L{line_end})\n\n"
                )
                focal_code = header + code_text

        # Strategy-specific mock policy formulation
        mock_policy: dict[str, str] = {}
        if strategy == "unit":
            mock_policy = {
                "isolation": "Isolate target in memory; mock external DB/network/filesystem I/O; never mock the target itself.",
                "forbid_mock": f"Do not mock the target {target_symbol} or its internal business logic.",
                "allowed_mock": "External DB connections, network HTTP calls, filesystem I/O.",
            }
        elif strategy == "integration":
            mock_policy = {
                "isolation": "Exercise full FastAPI TestClient -> Service -> SQLite flow; forbid mocking internal services or the database; only mock external 3rd-party APIs.",
                "forbid_mock": "Do not mock internal services, dependency injection providers, or SQLite database.",
                "allowed_mock": "External 3rd-party payment gateways, third-party notification APIs, external webhooks.",
            }
        elif strategy == "regression":
            is_entry = bool(target_attrs.get("is_entry_point", False))
            base_isolation = (
                "Exercise full FastAPI TestClient -> Service -> SQLite flow; forbid mocking internal services or the database; only mock external 3rd-party APIs."
                if is_entry
                else "Isolate target in memory; mock external DB/network/filesystem I/O; never mock the target itself."
            )
            forbid_rule = (
                "Do not mock internal services or the database."
                if is_entry
                else f"Do not mock the target {target_symbol}."
            )
            mock_policy = {
                "isolation": f"{base_isolation} Require Fail-to-Pass bug reproduction targeting the modified logic.",
                "forbid_mock": forbid_rule,
                "allowed_mock": "External 3rd-party APIs only.",
                "fail_to_pass": "Mandatory Fail-to-Pass check: test must reproduce defect on buggy snapshot and pass on fixed code.",
            }

        # Existing fixtures discovery
        existing_fixtures = find_conftest_fixtures(inst_wpath)

        return ContextBundle(
            strategy=strategy,
            target_node_id=canonical_target,
            target_symbol=target_symbol,
            source_file=source_file,
            line_span=(line_start, line_end),
            cyclomatic_complexity=cyclomatic_complexity,
            focal_code=focal_code,
            dependency_code=dependency_code,
            descriptive_context=descriptive_context,
            mock_policy=mock_policy,
            existing_fixtures=existing_fixtures,
        )


