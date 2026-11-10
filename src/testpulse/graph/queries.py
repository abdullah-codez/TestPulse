"""
TestPulse — Graph Queries & Target Selection
Adapted from Graphify (Graphify-Labs/graphify: analyze.py).
Provides God node discovery, circular import detection, unit/integration target selection,
and 2-hop blast radius computation.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

# Builtin noise labels to exclude from God node ranking
_NOISE_LABELS: frozenset[str] = frozenset({
    "str", "int", "float", "bool", "dict", "list", "set", "tuple",
    "object", "None", "True", "False", "__init__", "Base", "BaseModel",
    "Settings", "APIRouter", "FastAPI", "AsyncSession", "Depends",
})


def _is_file_node(G: nx.DiGraph, node_id: str) -> bool:
    """True if node represents a file."""
    return G.nodes[node_id].get("node_type") == "file"


def god_nodes(G: nx.DiGraph, top_n: int = 10) -> list[dict[str, Any]]:
    """
    Returns the top_n most-connected real entities (functions, methods, classes)
    excluding file hub nodes and framework noise labels.
    """
    degree = dict(G.degree())
    sorted_nodes = sorted(degree.items(), key=lambda x: x[1], reverse=True)

    result: list[dict[str, Any]] = []
    for node_id, deg in sorted_nodes:
        if node_id not in G.nodes:
            continue
        attrs = G.nodes[node_id]
        if _is_file_node(G, node_id):
            continue
        label = attrs.get("label", "")
        if label in _NOISE_LABELS or label.startswith("__"):
            continue

        start = attrs.get("line_start", 0)
        end = attrs.get("line_end", 0)
        line_count = (end - start + 1) if (end and start) else 0

        result.append({
            "id": node_id,
            "symbol": label,
            "label": label,
            "node_type": attrs.get("node_type", "function"),
            "source_file": attrs.get("source_file", ""),
            "degree": deg,
            "in_degree": G.in_degree(node_id),
            "out_degree": G.out_degree(node_id),
            "cyclomatic_complexity": attrs.get("cyclomatic_complexity", 1),
            "line_start": start,
            "line_end": end,
            "line_count": line_count,
        })
        if len(result) >= top_n:
            break

    return result


def find_import_cycles(
    G: nx.DiGraph,
    max_cycle_length: int = 5,
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """
    Detects circular import dependencies at the file level.
    Builds a directed file-level graph from 'imports_from' edges and discovers simple cycles.
    """
    file_graph = nx.DiGraph()

    for u, v, data in G.edges(data=True):
        if data.get("relation") != "imports_from":
            continue
        u_file = G.nodes.get(u, {}).get("source_file", u)
        v_file = G.nodes.get(v, {}).get("source_file", v)
        if u_file and v_file and u_file != v_file:
            file_graph.add_edge(u_file, v_file)

    if not file_graph.edges():
        return []

    cycles: list[list[str]] = []
    try:
        for cycle in nx.simple_cycles(file_graph, length_bound=max_cycle_length):
            if len(cycle) <= max_cycle_length:
                cycles.append(cycle)
            if len(cycles) >= top_n * 5:
                break
    except TypeError:
        # Compatibility with older networkx versions without length_bound
        for cycle in nx.simple_cycles(file_graph):
            if len(cycle) <= max_cycle_length:
                cycles.append(cycle)
            if len(cycles) >= top_n * 5:
                break

    # Sort by length and normalize cycles to deduplicate rotations
    cycles.sort(key=len)
    seen: set[tuple[str, ...]] = set()
    unique_cycles: list[list[str]] = []

    for cycle in cycles:
        if not cycle:
            continue
        min_idx = cycle.index(min(cycle))
        normalized = tuple(cycle[min_idx:] + cycle[:min_idx])
        if normalized not in seen:
            seen.add(normalized)
            unique_cycles.append(list(normalized))
            if len(unique_cycles) >= top_n:
                break

    return [
        {"cycle": c, "length": len(c), "description": " -> ".join(c + [c[0]])}
        for c in unique_cycles
    ]


def get_node_line_count(attrs: dict[str, Any]) -> int:
    """Safely extracts line count (line_end - line_start + 1) from node attributes."""
    start = attrs.get("line_start")
    end = attrs.get("line_end")
    if start is not None and end is not None:
        try:
            return max(0, int(end) - int(start) + 1)
        except (ValueError, TypeError):
            return 0
    return 0


def is_trivial_function(attrs: dict[str, Any]) -> bool:
    """
    Returns True if a node attribute dictionary represents a trivial function/method
    (cyclomatic_complexity <= 1 and line_count < 6).
    """
    if attrs.get("node_type") not in ("function", "method"):
        return False
    try:
        comp = int(attrs.get("cyclomatic_complexity", 1) or 1)
    except (ValueError, TypeError):
        comp = 1
    lines = get_node_line_count(attrs)
    return comp <= 1 and lines < 6


# Helper alias
is_trivial_node = is_trivial_function


def select_unit_targets(G: nx.DiGraph, max_targets: int = 5) -> list[dict[str, Any]]:
    """
    Ranks business logic and functions by topological significance and complexity
    while filtering out trivial getters/setters (cyclomatic_complexity <= 1 and < 6 lines)
    and framework boilerplate.
    """
    candidates: list[dict[str, Any]] = []

    for node_id, attrs in G.nodes(data=True):
        node_type = attrs.get("node_type")
        if node_type not in ("function", "method"):
            continue

        label = str(attrs.get("label", ""))
        if label.startswith("__") or label in _NOISE_LABELS:
            continue

        # Filter out trivial getters, one-line properties, pass statements
        if is_trivial_function(attrs):
            continue

        try:
            complexity = int(attrs.get("cyclomatic_complexity", 1) or 1)
        except (ValueError, TypeError):
            complexity = 1
        line_start = attrs.get("line_start", 0)
        line_end = attrs.get("line_end", 0)
        line_count = get_node_line_count(attrs)

        in_deg = G.in_degree(node_id)
        out_deg = G.out_degree(node_id)
        # Target score combines complexity with connectivity
        score = (complexity * 2.0) + (in_deg * 1.5) + (out_deg * 1.0)

        candidates.append({
            "node_id": node_id,
            "symbol": label,
            "node_type": node_type,
            "source_file": attrs.get("source_file", ""),
            "line_start": line_start,
            "line_end": line_end,
            "line_count": line_count,
            "cyclomatic_complexity": complexity,
            "in_degree": in_deg,
            "out_degree": out_deg,
            "score": score,
            "reason": f"High business logic complexity ({complexity}) and callers ({in_deg})",
        })

    # Sort descending by score
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:max_targets]


def select_integration_targets(G: nx.DiGraph, max_targets: int = 5) -> list[dict[str, Any]]:
    """
    Identifies verified FastAPI entry points and traces their downstream
    multi-hop dependencies (services, models, databases).
    """
    targets: list[dict[str, Any]] = []

    for node_id, attrs in G.nodes(data=True):
        if not attrs.get("is_entry_point"):
            continue

        # Downstream dependencies: BFS traversal of successors
        downstream: list[str] = []
        for successor in G.successors(node_id):
            succ_attrs = G.nodes.get(successor, {})
            succ_label = succ_attrs.get("label", successor)
            succ_file = succ_attrs.get("source_file", "")
            downstream.append(f"{succ_file}::{succ_label}")

        targets.append({
            "node_id": node_id,
            "symbol": attrs.get("label", ""),
            "source_file": attrs.get("source_file", ""),
            "line_start": attrs.get("line_start"),
            "line_end": attrs.get("line_end"),
            "http_method": attrs.get("http_method", "GET"),
            "route_path": attrs.get("route_path", ""),
            "dependencies": attrs.get("dependencies", []),
            "downstream_targets": downstream,
            "downstream_count": len(downstream),
        })

    # Sort by downstream dependency count (richer integration scenarios first)
    targets.sort(key=lambda x: len(x["downstream_targets"]), reverse=True)
    return targets[:max_targets]


def compute_blast_radius(G: nx.DiGraph, modified_nodes: list[str] | set[str]) -> set[str]:
    """
    Calculates the 2-hop blast radius of modified symbols for regression targeting:
    Radius = ModifiedNodes ∪ Callers²(in) ∪ Dependencies¹(out)

    - Callers (predecessors): traced up to 2 hops backwards (direct callers and callers of callers).
    - Dependencies (successors): traced 1 hop forwards (immediate downstream callee/model dependencies).
    """
    radius: set[str] = set()

    for node in modified_nodes:
        if node not in G.nodes:
            continue
        radius.add(node)

        # 1-hop downstream dependencies (out-edges)
        for dep in G.successors(node):
            radius.add(dep)

        # 1-hop upstream callers (in-edges)
        hop1_callers: set[str] = set()
        for caller in G.predecessors(node):
            hop1_callers.add(caller)
            radius.add(caller)

        # 2-hop upstream callers (callers of callers)
        for c1 in hop1_callers:
            for c2 in G.predecessors(c1):
                radius.add(c2)

    return radius
