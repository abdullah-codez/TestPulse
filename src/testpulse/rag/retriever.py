"""
TestPulse — Dual-Pipeline RAG Retriever
Combines exact topological graph traversal (Pipeline A: Graph Walk) with
semantic vector search (Pipeline B: Blindspot Sweeper) to construct unified context.
Enforces strict lazy open/close lifecycle on QdrantClient to prevent database locks.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import networkx as nx
from qdrant_client import QdrantClient, models

from testpulse.core.config import settings
from testpulse.rag.embedder import get_embedding


def _resolve_target_node_id(G: nx.DiGraph, query_id: str) -> str:
    """
    Resolves query_id to an exact node_id in G.
    Handles shorthand symbol names (e.g. 'calculate_discount' -> 'services/...::calculate_discount').
    """
    if query_id in G:
        return query_id

    for node, attrs in G.nodes(data=True):
        if attrs.get("label") == query_id:
            return str(node)
        if str(node).endswith(f"::{query_id}"):
            return str(node)

    return query_id


def retrieve_context_artifacts(
    G: nx.DiGraph,
    target_node_id: str,
    hop_depth: int = 1,
    collection_name: str = "testpulse_codebase",
    client_path: str | Path | None = None,
    embedder_fn: Callable[[str], list[float]] | None = None,
) -> dict[str, Any]:
    """
    Dual-Pipeline Context Artifact Retriever:
    Retrieves separated context chunks for a target node:
    - focal_chunk: The exact chunk string matching canonical target_node_id.
    - dependency_chunks: List of other code chunks retrieved via Pipeline A (graph walk).
    - descriptive_chunks: List of documentation/fixture chunks retrieved via Pipeline B (semantic sweeper).
    """
    canonical_target = _resolve_target_node_id(G, target_node_id)
    target_path = Path(client_path or settings.qdrant_path)

    # ------------------------------------------------------------------
    # Step 1: Discover Graph Walk Node IDs (Pipeline A Scope)
    # ------------------------------------------------------------------
    graph_node_ids: set[str] = {canonical_target}
    frontier: set[str] = {canonical_target}

    for _ in range(max(1, hop_depth)):
        next_frontier: set[str] = set()
        for curr in frontier:
            if curr in G:
                for pred in G.predecessors(curr):
                    if pred not in graph_node_ids:
                        graph_node_ids.add(str(pred))
                        next_frontier.add(str(pred))
                for succ in G.successors(curr):
                    if succ not in graph_node_ids:
                        graph_node_ids.add(str(succ))
                        next_frontier.add(str(succ))
        frontier = next_frontier

    focal_chunk: str = ""
    dependency_chunks: list[str] = []
    descriptive_chunks: list[str] = []

    # ------------------------------------------------------------------
    # Step 2: Lazy Qdrant Client Operations
    # ------------------------------------------------------------------
    client = QdrantClient(path=str(target_path))
    try:
        if not client.collection_exists(collection_name):
            return {
                "focal_chunk": "",
                "dependency_chunks": [],
                "descriptive_chunks": [],
            }

        # --- Pipeline A: Graph Walk (Exact Match via Payload Filter) ---
        pipeline_a_node_ids: set[str] = set()

        if graph_node_ids:
            records, _ = client.scroll(
                collection_name=collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="node_id",
                            match=models.MatchAny(any=list(graph_node_ids)),
                        )
                    ]
                ),
                limit=100,
                with_payload=True,
            )
            for r in records:
                if r.payload and "text_content" in r.payload:
                    txt = str(r.payload["text_content"])
                    nid = str(r.payload.get("node_id", ""))
                    pipeline_a_node_ids.add(nid)
                    if nid == canonical_target:
                        focal_chunk = txt
                    else:
                        dependency_chunks.append(txt)

        # --- Pipeline B: Semantic Match (The Blindspot Sweeper) ---
        target_attrs: dict[str, Any] = G.nodes.get(canonical_target, {})
        target_label = target_attrs.get("label", canonical_target)
        target_doc = target_attrs.get("docstring", "") or ""
        query_text = f"{target_label} {target_doc}".strip() or canonical_target

        embed_func = embedder_fn or get_embedding
        query_vector = embed_func(query_text)

        must_not_conditions: list[models.Condition] = []
        if pipeline_a_node_ids:
            must_not_conditions.append(
                models.FieldCondition(
                    key="node_id",
                    match=models.MatchAny(any=list(pipeline_a_node_ids)),
                )
            )

        query_res = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=models.Filter(must_not=must_not_conditions) if must_not_conditions else None,
            limit=2,
            with_payload=True,
        )

        for p in query_res.points:
            if p.payload and "text_content" in p.payload:
                descriptive_chunks.append(str(p.payload["text_content"]))

        return {
            "focal_chunk": focal_chunk,
            "dependency_chunks": dependency_chunks,
            "descriptive_chunks": descriptive_chunks,
        }
    finally:
        # Guarantee local SQLite/RocksDB lock is released immediately
        client.close()


def get_context_for_target(
    G: nx.DiGraph,
    target_node_id: str,
    hop_depth: int = 1,
    collection_name: str = "testpulse_codebase",
    client_path: str | Path | None = None,
    embedder_fn: Callable[[str], list[float]] | None = None,
) -> str:
    """
    Dual-Pipeline Context Retriever:
    Combines Pipeline A (Graph Walk) and Pipeline B (Blindspot Sweeper)
    into a unified context string separated by '\\n\\n---\\n\\n'.
    """
    artifacts = retrieve_context_artifacts(
        G=G,
        target_node_id=target_node_id,
        hop_depth=hop_depth,
        collection_name=collection_name,
        client_path=client_path,
        embedder_fn=embedder_fn,
    )
    combined: list[str] = []
    if artifacts["focal_chunk"].strip():
        combined.append(artifacts["focal_chunk"].strip())
    combined.extend(t.strip() for t in artifacts["dependency_chunks"] if t.strip())
    combined.extend(t.strip() for t in artifacts["descriptive_chunks"] if t.strip())
    return "\n\n---\n\n".join(combined)

