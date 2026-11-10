"""
TestPulse — Graph & AST Diff Engine
Adapted from Graphify (Graphify-Labs/graphify: analyze.py).
Combines NetworkX structural graph diffing with SHA-256 AST body hash comparisons
to detect internal function logic edits even when signatures and edges remain static.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from testpulse.graph.queries import compute_blast_radius


@dataclass
class GraphDiff:
    """Encapsulates the structural and logic differences between two graph states."""

    added_nodes: set[str]
    removed_nodes: set[str]
    modified_nodes: set[str]
    added_edges: list[dict[str, Any]]
    removed_edges: list[dict[str, Any]]
    blast_radius: set[str]
    summary: str
    modified_details: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blast_radius_nodes(self) -> list[str]:
        return sorted(self.blast_radius)

    @property
    def blast_radius_count(self) -> int:
        return len(self.blast_radius)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added_nodes": sorted(self.added_nodes),
            "removed_nodes": sorted(self.removed_nodes),
            "modified_nodes": sorted(self.modified_nodes),
            "modified_details": self.modified_details,
            "added_edges": self.added_edges,
            "removed_edges": self.removed_edges,
            "blast_radius_nodes": self.blast_radius_nodes,
            "blast_radius_count": self.blast_radius_count,
            "summary": self.summary,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


def compute_graph_diff(
    G_old: nx.DiGraph,
    G_new: nx.DiGraph,
    hashes_old: dict[str, str],
    hashes_new: dict[str, str],
) -> GraphDiff:
    """
    Compares two graph snapshots and their AST body hashes.
    Identifies:
      - Added / removed nodes
      - Added / removed edges
      - Modified nodes (internal logic changes detected via SHA-256 hash drift)
      - The 2-hop regression blast radius over all touched symbols
    """
    old_nodes = set(G_old.nodes())
    new_nodes = set(G_new.nodes())

    added_node_ids = new_nodes - old_nodes
    removed_node_ids = old_nodes - new_nodes
    common_node_ids = old_nodes & new_nodes

    # Detect internal modifications via AST body hash drift
    modified_node_ids: set[str] = set()
    for nid in common_node_ids:
        h_old = hashes_old.get(nid)
        h_new = hashes_new.get(nid)
        if (
            h_old
            and h_new
            and h_old != h_new
            and G_new.nodes[nid].get("node_type") != "file"
        ):
            modified_node_ids.add(nid)

    # Edge diffs
    def edge_key(u: str, v: str, data: dict[str, Any]) -> tuple[str, str, str]:
        return (u, v, data.get("relation", ""))

    old_edges = {edge_key(u, v, d): d for u, v, d in G_old.edges(data=True)}
    new_edges = {edge_key(u, v, d): d for u, v, d in G_new.edges(data=True)}

    added_edge_keys = set(new_edges) - set(old_edges)
    removed_edge_keys = set(old_edges) - set(new_edges)

    added_nodes_list = [
        {"id": n, "label": G_new.nodes[n].get("label", n), "type": G_new.nodes[n].get("node_type")}
        for n in sorted(added_node_ids)
    ]
    removed_nodes_list = [
        {"id": n, "label": G_old.nodes[n].get("label", n), "type": G_old.nodes[n].get("node_type")}
        for n in sorted(removed_node_ids)
    ]
    modified_nodes_list = [
        {
            "id": n,
            "label": G_new.nodes[n].get("label", n),
            "type": G_new.nodes[n].get("node_type"),
            "old_hash": hashes_old.get(n, "")[:12],
            "new_hash": hashes_new.get(n, "")[:12],
        }
        for n in sorted(modified_node_ids)
    ]

    added_edges_list = [
        {"source": k[0], "target": k[1], "relation": k[2]}
        for k in sorted(added_edge_keys)
    ]
    removed_edges_list = [
        {"source": k[0], "target": k[1], "relation": k[2]}
        for k in sorted(removed_edge_keys)
    ]

    # Compute regression blast radius over modified and added nodes
    touched_nodes = modified_node_ids | added_node_ids
    blast_radius = compute_blast_radius(G_new, touched_nodes)

    summary_parts: list[str] = []
    if modified_nodes_list:
        summary_parts.append(f"{len(modified_nodes_list)} modified symbol{'s' if len(modified_nodes_list) != 1 else ''}")
    if added_nodes_list:
        summary_parts.append(f"{len(added_nodes_list)} added node{'s' if len(added_nodes_list) != 1 else ''}")
    if removed_nodes_list:
        summary_parts.append(f"{len(removed_nodes_list)} removed node{'s' if len(removed_nodes_list) != 1 else ''}")
    if added_edges_list:
        summary_parts.append(f"{len(added_edges_list)} new edge{'s' if len(added_edges_list) != 1 else ''}")
    if blast_radius:
        summary_parts.append(f"{len(blast_radius)} nodes in 2-hop blast radius")

    summary = ", ".join(summary_parts) if summary_parts else "No structural or logic changes detected"

    return GraphDiff(
        added_nodes=added_node_ids,
        removed_nodes=removed_node_ids,
        modified_nodes=modified_node_ids,
        added_edges=added_edges_list,
        removed_edges=removed_edges_list,
        blast_radius=blast_radius,
        summary=summary,
        modified_details=modified_nodes_list,
    )
