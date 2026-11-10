"""
TestPulse — Cross-File Edge Resolver
Adapted from Graphify (Graphify-Labs/graphify: resolution.py & build.py).
Implements 2-pass symbol and call resolution between modules, classes, and functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from testpulse.graph.ast_extractor import SymbolNode


@dataclass
class ResolvedEdge:
    """Represents a directed relationship between two graph nodes."""

    source: str
    target: str
    relation: str  # "contains" | "imports_from" | "calls" | "inherits" | "depends_on"
    confidence: str  # "EXTRACTED" | "INFERRED"
    weight: float = 1.0
    source_file: str = ""
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "confidence": self.confidence,
            "weight": self.weight,
            "source_file": self.source_file,
            "line": self.line,
        }


class CrossFileResolver:
    """
    Resolves multi-file symbol relationships using explicit imports,
    containment hierarchies, and cross-module call invocations.
    """

    def __init__(self, nodes: list[SymbolNode], entry_points: dict[str, dict[str, Any]] | None = None) -> None:
        self.nodes = nodes
        self.nodes_by_id: dict[str, SymbolNode] = {n.id: n for n in nodes}
        self.entry_points = entry_points or {}

        # Fast lookup indexes
        # file_path -> File SymbolNode
        self.file_nodes: dict[str, SymbolNode] = {n.source_file: n for n in nodes if n.node_type == "file"}

        # symbol_name -> list of nodes declaring this symbol
        self.symbols_by_name: dict[str, list[SymbolNode]] = {}
        for n in nodes:
            if n.node_type in ("function", "method", "class"):
                self.symbols_by_name.setdefault(n.label, []).append(n)

        # file_path -> dict of local symbols (label -> node)
        self.file_symbols: dict[str, dict[str, SymbolNode]] = {}
        for n in nodes:
            if n.node_type in ("function", "method", "class"):
                self.file_symbols.setdefault(n.source_file, {})[n.label] = n

    def resolve(self) -> list[ResolvedEdge]:
        """Runs the two-pass edge resolution and returns all directed edges."""
        edges: list[ResolvedEdge] = []
        seen_edges: set[tuple[str, str, str]] = set()

        def add_edge(
            src: str,
            tgt: str,
            rel: str,
            conf: str,
            weight: float = 1.0,
            src_file: str = "",
            line: int | None = None,
        ) -> None:
            if src == tgt:
                return
            key = (src, tgt, rel)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append(ResolvedEdge(
                    source=src,
                    target=tgt,
                    relation=rel,
                    confidence=conf,
                    weight=weight,
                    source_file=src_file,
                    line=line,
                ))

        # -------------------------------------------------------------
        # PASS 1: EXTRACTED structural edges (contains, imports, depends_on)
        # -------------------------------------------------------------
        for node in self.nodes:
            # Containment: file contains top-level classes/functions, class contains methods
            if node.parent_id and node.parent_id in self.nodes_by_id:
                add_edge(
                    src=node.parent_id,
                    tgt=node.id,
                    rel="contains",
                    conf="EXTRACTED",
                    src_file=node.source_file,
                    line=node.line_start,
                )

            # File imports: file imports from target file
            if node.node_type == "file" and node.imports:
                for imp in node.imports:
                    mod = imp.get("module", "")
                    # Match module path to discovered files
                    target_file = self._resolve_module_to_file(mod, node.source_file)
                    if target_file and target_file in self.file_nodes:
                        add_edge(
                            src=node.id,
                            tgt=self.file_nodes[target_file].id,
                            rel="imports_from",
                            conf="EXTRACTED",
                            src_file=node.source_file,
                            line=imp.get("line"),
                        )

            # FastAPI Depends(...) dependencies
            if node.id in self.entry_points:
                deps = self.entry_points[node.id].get("dependencies", [])
                for dep_name in deps:
                    target_sym = self._resolve_symbol_in_scope(dep_name, node.source_file)
                    if target_sym:
                        add_edge(
                            src=node.id,
                            tgt=target_sym.id,
                            rel="depends_on",
                            conf="EXTRACTED",
                            src_file=node.source_file,
                            line=node.line_start,
                        )

        # -------------------------------------------------------------
        # PASS 2: INFERRED & Cross-Module Call Resolution
        # -------------------------------------------------------------
        for node in self.nodes:
            if not node.calls:
                continue

            for call_name in node.calls:
                # 1. Check local file symbols first (methods or functions in same file)
                local_sym = self.file_symbols.get(node.source_file, {}).get(call_name)
                if local_sym and local_sym.id != node.id:
                    add_edge(
                        src=node.id,
                        tgt=local_sym.id,
                        rel="calls",
                        conf="EXTRACTED",
                        src_file=node.source_file,
                        line=node.line_start,
                    )
                    continue

                # 2. Check explicit imports of the source file
                imported_sym = self._resolve_imported_symbol(call_name, node.source_file)
                if imported_sym:
                    add_edge(
                        src=node.id,
                        tgt=imported_sym.id,
                        rel="calls",
                        conf="EXTRACTED",
                        src_file=node.source_file,
                        line=node.line_start,
                    )
                    continue

                # 3. Inferred resolution: unique global symbol match
                candidates = self.symbols_by_name.get(call_name, [])
                if len(candidates) == 1:
                    add_edge(
                        src=node.id,
                        tgt=candidates[0].id,
                        rel="calls",
                        conf="INFERRED",
                        weight=0.7,
                        src_file=node.source_file,
                        line=node.line_start,
                    )

        return edges

    def _resolve_module_to_file(self, module_str: str, from_file: str) -> str | None:
        """Translates Python dot-import or JS path import into a relative file path."""
        if not module_str:
            return None

        # Clean relative JS/TS imports: "./routes/orders" or "../services/discount"
        clean_mod = module_str.lstrip("./").replace("\\", "/")

        # Check Python dot notation: "app.services.discount" -> "app/services/discount"
        dot_as_path = module_str.replace(".", "/")

        for fpath in self.file_nodes:
            # Exact match without extension
            base_no_ext = fpath.rsplit(".", 1)[0]
            if base_no_ext.endswith(clean_mod) or base_no_ext.endswith(dot_as_path):
                return fpath
            # Check package __init__.py match
            if fpath.endswith(f"{clean_mod}/__init__.py") or fpath.endswith(f"{dot_as_path}/__init__.py"):
                return fpath

        return None

    def _resolve_imported_symbol(self, symbol_name: str, from_file: str) -> SymbolNode | None:
        """Finds if from_file explicitly imported symbol_name and returns its target node."""
        file_node = self.file_nodes.get(from_file)
        if not file_node or not file_node.imports:
            return None

        for imp in file_node.imports:
            imp_name = imp.get("name")
            if not imp_name or not isinstance(imp_name, str):
                continue
            imp_alias = imp.get("alias")
            target_name = imp_alias if (imp_alias and isinstance(imp_alias, str)) else imp_name

            if target_name == symbol_name:
                mod = str(imp.get("module", ""))
                target_file = self._resolve_module_to_file(mod, from_file)
                if target_file:
                    target_sym = self.file_symbols.get(target_file, {}).get(imp_name)
                    if target_sym:
                        return target_sym

        return None

    def _resolve_symbol_in_scope(self, symbol_name: str, from_file: str) -> SymbolNode | None:
        """Looks up a symbol in local file scope or through imports."""
        # Check local file
        local = self.file_symbols.get(from_file, {}).get(symbol_name)
        if local:
            return local
        # Check imports
        return self._resolve_imported_symbol(symbol_name, from_file)
