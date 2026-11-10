"""
TestPulse — FastAPI Entry Points Detector
Inspects decorated functions to discover API routes, HTTP methods, route paths,
and dependency injection references (Depends).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from testpulse.graph.ast_extractor import SymbolNode

# Regex pattern matching FastAPI / Starlette route decorators
# e.g., @app.get("/items"), @router.post("/orders", response_model=Order)
_ROUTE_DECORATOR_PATTERN = re.compile(
    r"@(?:app|router|api_router)\.(get|post|put|delete|patch|options|head)\s*\(\s*(['\"])(.*?)\2",
    re.IGNORECASE,
)

# Regex pattern for detecting Depends(...) in parameters or decorator
_DEPENDS_PATTERN = re.compile(r"Depends\s*\(\s*([a-zA-Z0-9_]+)\s*\)")


def detect_entry_point(node: SymbolNode) -> dict[str, Any] | None:
    """
    Checks if a SymbolNode is a FastAPI entry point based on its decorators.
    Returns route metadata if matched, otherwise None.
    """
    if not node.decorators or node.node_type not in ("function", "method"):
        return None

    for dec in node.decorators:
        match = _ROUTE_DECORATOR_PATTERN.search(dec)
        if match:
            http_method = match.group(1).upper()
            route_path = match.group(3)

            # Discover dependencies inside the decorator and function parameters
            dependencies: list[str] = []
            for dep_match in _DEPENDS_PATTERN.finditer(dec):
                dependencies.append(dep_match.group(1))

            # Also check parameter definitions in body source for Depends(...)
            if node.body_source:
                for dep_match in _DEPENDS_PATTERN.finditer(node.body_source):
                    dep_name = dep_match.group(1)
                    if dep_name not in dependencies:
                        dependencies.append(dep_name)

            return {
                "is_entry_point": True,
                "http_method": http_method,
                "route_path": route_path,
                "dependencies": dependencies,
            }

    return None


def annotate_entry_points(nodes: list[SymbolNode]) -> dict[str, dict[str, Any]]:
    """
    Scans all nodes, mutates node route attributes in-place,
    and returns a mapping of node_id -> route_metadata for all discovered FastAPI entry points.
    """
    entry_points: dict[str, dict[str, Any]] = {}
    for node in nodes:
        route_meta = detect_entry_point(node)
        if route_meta:
            node.is_entry_point = True
            node.http_method = route_meta["http_method"]
            node.route_path = route_meta["route_path"]
            node.dependencies = list(route_meta["dependencies"])
            entry_points[node.id] = route_meta
    return entry_points
