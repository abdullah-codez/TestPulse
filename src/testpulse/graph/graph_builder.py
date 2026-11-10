"""
TestPulse — Graph Builder
Constructs a native NetworkX directed graph (nx.DiGraph) from extracted AST nodes
and resolved cross-file edges. Supports JSON persistence and directional traversals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx

from testpulse.graph.ast_extractor import CodeASTExtractor, SymbolNode, scan_source_files
from testpulse.graph.ast_hasher import compute_hashes_for_nodes
from testpulse.graph.cross_file_resolver import CrossFileResolver, ResolvedEdge
from testpulse.graph.entry_points import annotate_entry_points


def build_graph(root_dir: str | Path) -> tuple[nx.DiGraph, dict[str, str]]:
    """
    Scans the repository, extracts symbols and body hashes, resolves cross-file
    edges, and returns an initialized NetworkX DiGraph along with AST hashes.
    """
    root = Path(root_dir).resolve()
    extractor = CodeASTExtractor(root)

    source_files = scan_source_files(root)
    all_nodes: list[SymbolNode] = []
    for f in source_files:
        all_nodes.extend(extractor.extract_file(f))

    # Calculate deterministic SHA-256 body hashes
    ast_hashes = compute_hashes_for_nodes(all_nodes)

    # Detect FastAPI entry points
    entry_point_annotations = annotate_entry_points(all_nodes)

    # Resolve cross-file containment, imports, and calls
    resolver = CrossFileResolver(all_nodes, entry_point_annotations)
    resolved_edges: list[ResolvedEdge] = resolver.resolve()

    # Construct NetworkX DiGraph
    G = nx.DiGraph()

    # Add nodes with all metadata
    for n in all_nodes:
        attrs: dict[str, Any] = {
            "label": n.label,
            "node_type": n.node_type,
            "source_file": n.source_file,
            "line_start": n.line_start,
            "line_end": n.line_end,
            "docstring": n.docstring,
            "parameters": n.parameters,
            "return_type": n.return_type,
            "cyclomatic_complexity": n.cyclomatic_complexity,
            "decorators": n.decorators,
            "parent_id": n.parent_id,
            "ast_hash": ast_hashes.get(n.id),
        }

        # Attach route metadata if entry point
        if n.id in entry_point_annotations:
            attrs.update(entry_point_annotations[n.id])
        else:
            attrs["is_entry_point"] = False

        G.add_node(n.id, **attrs)

    # Add edges with relations
    for e in resolved_edges:
        G.add_edge(
            e.source,
            e.target,
            relation=e.relation,
            confidence=e.confidence,
            weight=e.weight,
            source_file=e.source_file,
            line=e.line,
        )

    return G, ast_hashes


def export_graph_json(G: nx.DiGraph, out_path: str | Path) -> None:
    """Exports the graph to a JSON file using NetworkX node-link format."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(G)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_graph_json(in_path: str | Path) -> nx.DiGraph:
    """Loads a NetworkX DiGraph from a node-link JSON file."""
    path = Path(in_path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    graph = nx.node_link_graph(data, directed=True)
    if isinstance(graph, nx.DiGraph):
        return graph
    return nx.DiGraph(graph)


def export_hashes_json(hashes: dict[str, str], out_path: str | Path) -> None:
    """Exports AST hashes mapping to a JSON file."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(hashes, f, indent=2, sort_keys=True)


def load_hashes_json(in_path: str | Path) -> dict[str, str]:
    """Loads AST hashes mapping from a JSON file."""
    path = Path(in_path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {str(k): str(v) for k, v in data.items()}
