"""
TestPulse — Dual-Strategy Repository Chunker
Extracts granular cAST code chunks from AST knowledge graph nodes and
semantically chunks descriptive workspace files (e.g. Markdown, conftest.py).
Injects rich contextual metadata headers into every chunk before embedding.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import networkx as nx

from testpulse.graph.ast_extractor import DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_FILES


def _extract_source_lines(
    file_path: Path,
    line_start: int,
    line_end: int,
    file_cache: dict[Path, list[str]],
) -> str:
    """Reads 1-indexed line range [line_start, line_end] inclusive from file_path."""
    if file_path not in file_cache:
        try:
            file_cache[file_path] = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""

    lines = file_cache[file_path]
    # Convert 1-indexed to 0-indexed slicing
    start_idx = max(0, line_start - 1)
    end_idx = min(len(lines), line_end)
    return "\n".join(lines[start_idx:end_idx])


def _get_callers_for_node(G: nx.DiGraph, node_id: str) -> list[str]:
    """
    Finds direct callers / dependent symbols for a node in G.
    Filters out file and container class nodes to focus on actionable calling functions/endpoints.
    """
    callers: list[str] = []
    for pred in G.predecessors(node_id):
        pred_data = G.nodes.get(pred, {})
        pred_type = pred_data.get("node_type")
        edge_data = G.edges.get((pred, node_id), {})
        relation = edge_data.get("relation", "")

        # Skip containment relations (class -> method or file -> function)
        if relation == "contains":
            continue

        # Prefer callable nodes
        if (
            pred_type in ("function", "method")
            or relation in ("calls", "depends_on")
            or pred_type not in ("file", "class")
        ):
            callers.append(str(pred_data.get("label", pred)))

    return sorted(set(callers))


def chunk_markdown_file(file_path: Path, rel_path: str) -> list[dict[str, Any]]:
    """
    Semantically splits a Markdown file into sections based on markdown headings.
    Injects contextual descriptive headers into every chunk.
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    lines = content.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_title = "Overview"
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("#"):
            if current_lines and any(ln.strip() for ln in current_lines):
                sections.append((current_title, current_lines))
                current_lines = []
            current_title = line.lstrip("#").strip() or "Section"
            current_lines.append(line)
        else:
            current_lines.append(line)

    if current_lines and any(ln.strip() for ln in current_lines):
        sections.append((current_title, current_lines))

    chunks: list[dict[str, Any]] = []
    for idx, (title, sec_lines) in enumerate(sections):
        sec_text = "\n".join(sec_lines).strip()
        if not sec_text:
            continue

        slug = re.sub(r"[^a-zA-Z0-9_\-]+", "-", title.lower()).strip("-")
        node_id = f"doc::{rel_path}#{slug or idx}"

        header = (
            f"# [TestPulse Descriptive Chunk]\n"
            f"# Node ID: {node_id}\n"
            f"# File: {rel_path}\n"
            f"# Section: {title}\n\n"
        )
        full_text = header + sec_text
        chunks.append({
            "node_id": node_id,
            "text_content": full_text,
            "metadata": {
                "type": "text",
                "node_id": node_id,
                "source_file": rel_path,
                "section": title,
            },
        })

    return chunks


def chunk_repository(G: nx.DiGraph, workspace_path: Path) -> list[dict[str, Any]]:
    """
    Dual-strategy repository chunker:
    1. Code (AST Chunking): Extracts exact code block for each AST symbol node
       (1 Node = 1 Chunk), prepending callers and location metadata.
    2. Descriptive Files (Text Chunking): Scans workspace for Markdown and fixture files,
       splitting semantically with metadata headers.

    Returns a list of chunk dicts: {"node_id": ..., "text_content": ..., "metadata": ...}.
    """
    workspace_path = Path(workspace_path).resolve()
    chunks: list[dict[str, Any]] = []
    file_cache: dict[Path, list[str]] = {}

    # ------------------------------------------------------------------
    # Strategy 1: Code AST Chunking
    # ------------------------------------------------------------------
    for node_id, attrs in G.nodes(data=True):
        node_type = attrs.get("node_type")
        # Skip top-level file containers; chunks represent actionable code units
        if node_type == "file":
            continue

        source_file = attrs.get("source_file")
        line_start = attrs.get("line_start")
        line_end = attrs.get("line_end")

        if not source_file or line_start is None or line_end is None:
            continue

        try:
            line_start_int = int(line_start)
            line_end_int = int(line_end)
        except (ValueError, TypeError):
            continue

        if line_start_int <= 0 or line_end_int < line_start_int:
            continue

        file_path = workspace_path / source_file if not Path(source_file).is_absolute() else Path(source_file)
        snippet = _extract_source_lines(file_path, line_start_int, line_end_int, file_cache)
        if not snippet.strip():
            continue

        callers = _get_callers_for_node(G, node_id)
        callers_str = ", ".join(callers) if callers else "None"

        rel_source = Path(source_file).as_posix()
        header = (
            f"# [TestPulse cAST Chunk]\n"
            f"# Node ID: {node_id}\n"
            f"# File: {rel_source} (L{line_start_int}-L{line_end_int})\n"
            f"# Callers: {callers_str}\n\n"
        )
        full_text = header + snippet

        chunks.append({
            "node_id": str(node_id),
            "text_content": full_text,
            "metadata": {
                "type": "code",
                "node_id": str(node_id),
                "symbol": str(attrs.get("label", "")),
                "node_type": str(node_type),
                "source_file": rel_source,
                "line_start": line_start_int,
                "line_end": line_end_int,
                "callers": callers,
                "cyclomatic_complexity": attrs.get("cyclomatic_complexity", 1),
                "is_entry_point": attrs.get("is_entry_point", False),
            },
        })

    # ------------------------------------------------------------------
    # Strategy 2: Descriptive Files (Text Chunking)
    # ------------------------------------------------------------------
    scanned_text_files: set[Path] = set()

    for root, dirs, files in os.walk(workspace_path):
        # Exclude internal / vendor / cache directories
        dirs[:] = [
            d for d in dirs
            if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")
        ]

        for file_name in files:
            if file_name in DEFAULT_IGNORE_FILES or file_name.startswith("."):
                continue

            file_path = Path(root) / file_name
            rel_path = file_path.relative_to(workspace_path).as_posix()

            # Handle Markdown files
            if file_path.suffix.lower() in (".md", ".markdown"):
                scanned_text_files.add(file_path)
                md_chunks = chunk_markdown_file(file_path, rel_path)
                chunks.extend(md_chunks)

            # Handle global fixture / conftest files not captured in AST graph
            elif file_name == "conftest.py" and rel_path not in G.nodes:
                scanned_text_files.add(file_path)
                try:
                    txt = file_path.read_text(encoding="utf-8", errors="replace").strip()
                    if txt:
                        node_id = f"fixture::{rel_path}"
                        header = (
                            f"# [TestPulse Descriptive Chunk]\n"
                            f"# Node ID: {node_id}\n"
                            f"# File: {rel_path}\n"
                            f"# Section: Pytest Fixtures\n\n"
                        )
                        chunks.append({
                            "node_id": node_id,
                            "text_content": header + txt,
                            "metadata": {
                                "type": "text",
                                "node_id": node_id,
                                "source_file": rel_path,
                                "section": "Pytest Fixtures",
                            },
                        })
                except OSError:
                    continue

    return chunks
