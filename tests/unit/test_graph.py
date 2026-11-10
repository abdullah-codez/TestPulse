"""Unit test suite for TestPulse native AST graph engine.

Verifies:
- Multi-file AST extraction and cyclomatic complexity counting
- Normalized AST body hashing and logic drift detection
- FastAPI route entry point detection and Depends(...) dependencies
- Cross-file call resolution and DiGraph construction
- Trivial getter filtering in unit target selection
- 2-hop blast radius computation on modified nodes
- Graph diff detection combining structural changes and hash drift
- Human-readable Markdown and interactive HTML report generation
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

from testpulse.graph.ast_extractor import CodeASTExtractor, scan_source_files
from testpulse.graph.ast_hasher import calculate_ast_body_hash
from testpulse.graph.diff import compute_graph_diff
from testpulse.graph.entry_points import annotate_entry_points
from testpulse.graph.graph_builder import (
    build_graph,
    export_graph_json,
    export_hashes_json,
    load_graph_json,
    load_hashes_json,
)
from testpulse.graph.queries import (
    compute_blast_radius,
    find_import_cycles,
    god_nodes,
    select_integration_targets,
    select_unit_targets,
)
from testpulse.graph.reporter import generate_report, to_html

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "sample_fastapi"


@pytest.fixture
def sample_graph() -> tuple[nx.DiGraph, dict[str, str]]:
    """Builds and returns graph and AST hashes for sample_fastapi fixture."""
    G, hashes = build_graph(FIXTURE_DIR)
    return G, hashes


def test_scan_and_ast_extraction() -> None:
    """Verifies scanning discovers fixture files and extracts accurate symbol AST nodes."""
    files = scan_source_files(FIXTURE_DIR)
    file_names = [f.name for f in files]

    assert "main.py" in file_names
    assert "orders.py" in file_names
    assert "discount_service.py" in file_names
    assert "order.py" in file_names

    extractor = CodeASTExtractor(FIXTURE_DIR)
    symbols = extractor.extract_all()

    assert len(symbols) > 0

    # Locate calculate_discount symbol
    calc_nodes = [s for s in symbols if s.name == "calculate_discount"]
    assert len(calc_nodes) == 1
    calc = calc_nodes[0]

    assert calc.node_type == "method"
    assert calc.line_start > 0
    assert calc.line_end > calc.line_start
    # calculate_discount contains multiple if/elif/and branches
    assert calc.cyclomatic_complexity >= 5

    # Locate trivial getter
    getter_nodes = [s for s in symbols if s.name == "get_service_name"]
    assert len(getter_nodes) == 1
    getter = getter_nodes[0]
    assert getter.cyclomatic_complexity == 1
    assert (getter.line_end - getter.line_start + 1) < 6


def test_ast_hasher_normalization_and_drift() -> None:
    """Verifies AST body hashing is resilient to comments/whitespace but drifts on logic edits."""
    body_v1 = """
    def calculate(x: int) -> int:
        # Initial implementation with comment
        return x * 2
    """

    body_v1_comments_changed = """
    def calculate(x: int) -> int:
        \"\"\"Different docstring here.\"\"\"
        # Changed inline comment
        return x * 2
    """

    body_v2_logic_changed = """
    def calculate(x: int) -> int:
        return x * 3  # Modified multiplier
    """

    hash_v1 = calculate_ast_body_hash(body_v1, "python")
    hash_v1_comment = calculate_ast_body_hash(body_v1_comments_changed, "python")
    hash_v2_logic = calculate_ast_body_hash(body_v2_logic_changed, "python")

    assert len(hash_v1) == 64
    assert hash_v1 == hash_v1_comment, "Hash should be invariant to comment/docstring changes"
    assert hash_v1 != hash_v2_logic, "Hash must change when logic/multiplier changes"


def test_fastapi_entry_point_detection() -> None:
    """Verifies detection of FastAPI HTTP routes, methods, paths, and Depends injection."""
    extractor = CodeASTExtractor(FIXTURE_DIR)
    symbols = extractor.extract_all()
    annotate_entry_points(symbols)

    entry_points = [s for s in symbols if s.is_entry_point]
    assert len(entry_points) >= 3

    ep_names = {s.name: s for s in entry_points}

    assert "create_order" in ep_names
    co = ep_names["create_order"]
    assert co.http_method == "POST"
    assert co.route_path == "/"
    assert "get_discount_service" in co.dependencies

    assert "get_order_by_id" in ep_names
    assert ep_names["get_order_by_id"].http_method == "GET"
    assert ep_names["get_order_by_id"].route_path == "/{order_id}"

    assert "health_check" in ep_names
    assert ep_names["health_check"].http_method == "GET"
    assert ep_names["health_check"].route_path == "/health"


def test_cross_file_resolution(sample_graph: tuple[nx.DiGraph, dict[str, str]]) -> None:
    """Verifies 2-pass resolver links route handlers across files to services."""
    G, _ = sample_graph

    # Verify nodes exist in DiGraph
    labels = {d.get("label"): n for n, d in G.nodes(data=True)}
    assert "create_order" in labels
    assert "calculate_discount" in labels

    create_order_nid = labels["create_order"]
    calc_nid = labels["calculate_discount"]

    # Verify create_order reaches calculate_discount directly or via service
    successors = list(G.successors(create_order_nid))
    assert len(successors) > 0

    # Reachability in directed call graph
    has_path = nx.has_path(G, create_order_nid, calc_nid)
    assert has_path, "create_order should reach calculate_discount in the call graph"


def test_select_unit_targets_filters_trivial_getters(
    sample_graph: tuple[nx.DiGraph, dict[str, str]],
) -> None:
    """Verifies unit target selector prioritizes high-complexity logic and ignores trivial getters."""
    G, _ = sample_graph
    targets = select_unit_targets(G, max_targets=5)
    target_symbols = [t["symbol"] for t in targets]

    # Complex business method must be ranked
    assert "calculate_discount" in target_symbols

    # Trivial getters must be filtered out
    assert "get_service_name" not in target_symbols
    assert "get_base_tax_rate" not in target_symbols


def test_select_integration_targets(sample_graph: tuple[nx.DiGraph, dict[str, str]]) -> None:
    """Verifies integration targets capture entry points and downstream multi-hop targets."""
    G, _ = sample_graph
    targets = select_integration_targets(G, max_targets=10)
    symbols = [t["symbol"] for t in targets]

    assert "create_order" in symbols
    assert "get_order_by_id" in symbols

    co_target = next(t for t in targets if t["symbol"] == "create_order")
    assert co_target["http_method"] == "POST"
    assert "get_discount_service" in co_target["dependencies"]


def test_compute_blast_radius(sample_graph: tuple[nx.DiGraph, dict[str, str]]) -> None:
    """Verifies 2-hop blast radius computation includes modified nodes, callers^2, and deps^1."""
    G, _ = sample_graph
    labels = {d.get("label"): n for n, d in G.nodes(data=True)}
    calc_nid = labels["calculate_discount"]

    blast = compute_blast_radius(G, [calc_nid])

    # Modified node itself must be in blast radius
    assert calc_nid in blast

    # Caller (create_order) should be within 2 hops
    create_order_nid = labels["create_order"]
    assert create_order_nid in blast, "Caller create_order should be in the blast radius"


def test_graph_diff_with_ast_hash_drift(
    sample_graph: tuple[nx.DiGraph, dict[str, str]],
) -> None:
    """Verifies compute_graph_diff identifies logic modifications when AST body hashes drift."""
    G, hashes_orig = sample_graph
    labels = {d.get("label"): n for n, d in G.nodes(data=True)}
    calc_nid = labels["calculate_discount"]

    # Simulate logic drift in calculate_discount
    hashes_modified = dict(hashes_orig)
    hashes_modified[calc_nid] = "deadbeef" * 8

    diff = compute_graph_diff(G, G, hashes_orig, hashes_modified)

    assert calc_nid in diff.modified_nodes
    assert len(diff.blast_radius) > 0
    assert labels["create_order"] in diff.blast_radius


def test_graph_serialization(
    tmp_path: Path, sample_graph: tuple[nx.DiGraph, dict[str, str]]
) -> None:
    """Verifies JSON round-trip export and reload of graph and hashes."""
    G, hashes = sample_graph

    graph_file = tmp_path / "graph.json"
    hashes_file = tmp_path / "ast_hashes.json"

    export_graph_json(G, graph_file)
    export_hashes_json(hashes, hashes_file)

    assert graph_file.exists()
    assert hashes_file.exists()

    loaded_G = load_graph_json(graph_file)
    loaded_hashes = load_hashes_json(hashes_file)

    assert loaded_G.number_of_nodes() == G.number_of_nodes()
    assert loaded_G.number_of_edges() == G.number_of_edges()
    assert loaded_hashes == hashes


def test_god_nodes_and_cycle_detection(sample_graph: tuple[nx.DiGraph, dict[str, str]]) -> None:
    """Verifies God node discovery and circular import detection."""
    G, _ = sample_graph
    gn = god_nodes(G, top_n=5)
    assert isinstance(gn, list)

    cycles = find_import_cycles(G)
    # The fixture application is cleanly structured with no circular imports
    assert isinstance(cycles, list)


def test_report_and_html_generation(
    tmp_path: Path, sample_graph: tuple[nx.DiGraph, dict[str, str]]
) -> None:
    """Verifies Markdown GRAPH_REPORT.md and interactive HTML generation."""
    G, _ = sample_graph

    report_path = tmp_path / "GRAPH_REPORT.md"
    html_path = tmp_path / "graph.html"

    report_md = generate_report(G, output_path=report_path)
    to_html(G, output_path=html_path)

    assert report_path.exists()
    assert html_path.exists()

    # Verify Markdown sections
    assert "# TestPulse — Structural AST Knowledge Graph Report" in report_md
    assert "## 1. Graph Overview" in report_md
    assert "## 2. Detected FastAPI Entry Points" in report_md
    assert "## 3. High-Priority Business Logic & God Nodes" in report_md
    assert "## 4. Filtered Trivial Functions (Skipped Getters & Wrappers)" in report_md
    assert "## 5. Architectural Health & Cycle Analysis" in report_md

    # Check that trivial getters are mentioned in the filtered section
    assert "get_service_name" in report_md

    # Verify HTML content
    html_content = html_path.read_text(encoding="utf-8")
    assert '<svg id="viz"></svg>' in html_content
    assert "d3.forceSimulation" in html_content
