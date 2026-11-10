"""
TestPulse — Native In-House AST Knowledge Graph Engine
Adapted from Graphify (Graphify-Labs/graphify).
"""

from testpulse.graph.ast_extractor import CodeASTExtractor, SymbolNode, scan_source_files
from testpulse.graph.ast_hasher import (
    calculate_ast_body_hash,
    compute_hashes_for_nodes,
    normalize_code_body,
)
from testpulse.graph.cross_file_resolver import CrossFileResolver, ResolvedEdge
from testpulse.graph.diff import GraphDiff, compute_graph_diff
from testpulse.graph.entry_points import annotate_entry_points, detect_entry_point
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
    get_node_line_count,
    god_nodes,
    is_trivial_function,
    is_trivial_node,
    select_integration_targets,
    select_unit_targets,
)
from testpulse.graph.reporter import generate_report, to_html

__all__ = [
    "CodeASTExtractor",
    "CrossFileResolver",
    "GraphDiff",
    "ResolvedEdge",
    "SymbolNode",
    "annotate_entry_points",
    "build_graph",
    "calculate_ast_body_hash",
    "compute_blast_radius",
    "compute_graph_diff",
    "compute_hashes_for_nodes",
    "detect_entry_point",
    "export_graph_json",
    "export_hashes_json",
    "find_import_cycles",
    "generate_report",
    "get_node_line_count",
    "god_nodes",
    "is_trivial_function",
    "is_trivial_node",
    "load_graph_json",
    "load_hashes_json",
    "normalize_code_body",
    "scan_source_files",
    "select_integration_targets",
    "select_unit_targets",
    "to_html",
]
