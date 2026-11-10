"""
TestPulse — In-House Multi-Language AST Extractor
Adapted from Graphify (Graphify-Labs/graphify: detect.py & extract.py).
Specialized strictly for Python and JavaScript/TypeScript.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tree_sitter_javascript as ts_javascript
import tree_sitter_python as ts_python
import tree_sitter_typescript as ts_typescript
from tree_sitter import Language, Node, Parser

# Initialize Language grammars once
PY_LANGUAGE = Language(ts_python.language())
JS_LANGUAGE = Language(ts_javascript.language())
TS_LANGUAGE = Language(ts_typescript.language_typescript())
TSX_LANGUAGE = Language(ts_typescript.language_tsx())

# Default directories and files to ignore during codebase scanning
DEFAULT_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".testpulse",
    ".vendor",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".turbo",
    "coverage",
    "htmlcov",
    ".idea",
    ".vscode",
})

DEFAULT_IGNORE_FILES: frozenset[str] = frozenset({
    ".DS_Store",
    "Thumbs.db",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
})

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
})

# Standard built-in identifiers to filter out from function calls
BUILTIN_CALL_FILTER: frozenset[str] = frozenset({
    # Python built-ins
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "classmethod", "compile", "complex", "delattr",
    "dict", "dir", "divmod", "enumerate", "eval", "exec", "filter",
    "float", "format", "frozenset", "getattr", "globals", "hasattr",
    "hash", "help", "hex", "id", "input", "int", "isinstance",
    "issubclass", "iter", "len", "list", "locals", "map", "max",
    "memoryview", "min", "next", "object", "oct", "open", "ord",
    "pow", "print", "property", "range", "repr", "reversed", "round",
    "set", "setattr", "slice", "sorted", "staticmethod", "str",
    "sum", "super", "tuple", "type", "vars", "zip", "__import__",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "RuntimeError", "AttributeError", "NotImplementedError",
    # JS/TS common built-ins
    "console.log", "console.error", "console.warn", "console.info",
    "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURI", "decodeURI",
    "String", "Number", "Boolean", "Array", "Object", "Function", "Symbol",
    "Error", "Promise", "RegExp", "Map", "Set", "WeakMap", "WeakSet",
    "JSON.stringify", "JSON.parse", "Math.floor", "Math.ceil", "Math.round",
    "Math.max", "Math.min", "Math.abs",
})


@dataclass
class SymbolNode:
    """Represents a code symbol extracted from the AST."""

    id: str
    label: str
    node_type: str  # "file" | "class" | "function" | "method"
    source_file: str
    line_start: int
    line_end: int
    docstring: str | None = None
    parameters: list[str] = field(default_factory=list)
    return_type: str | None = None
    cyclomatic_complexity: int = 1
    calls: list[str] = field(default_factory=list)
    imports: list[dict[str, Any]] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    parent_id: str | None = None
    body_source: str = ""
    is_entry_point: bool = False
    http_method: str | None = None
    route_path: str | None = None
    dependencies: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """Alias for label for convenient symbol naming."""
        return self.label

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "node_type": self.node_type,
            "source_file": self.source_file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "docstring": self.docstring,
            "parameters": self.parameters,
            "return_type": self.return_type,
            "cyclomatic_complexity": self.cyclomatic_complexity,
            "calls": self.calls,
            "imports": self.imports,
            "decorators": self.decorators,
            "parent_id": self.parent_id,
            "is_entry_point": self.is_entry_point,
            "http_method": self.http_method,
            "route_path": self.route_path,
            "dependencies": self.dependencies,
        }


def scan_source_files(root_dir: str | Path) -> list[Path]:
    """
    Recursively scans the root directory and returns a sorted list of supported
    source files, excluding ignored directories and vendor libraries.
    """
    root = Path(root_dir).resolve()
    discovered: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # In-place filter directories to avoid recursing into ignored trees
        dirnames[:] = [
            d for d in dirnames
            if d not in DEFAULT_IGNORE_DIRS and not d.endswith(".egg-info")
        ]

        for fname in filenames:
            if fname in DEFAULT_IGNORE_FILES:
                continue
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() in SUPPORTED_EXTENSIONS:
                discovered.append(fpath)

    discovered.sort()
    return discovered


def _get_parser_for_file(path: Path) -> Parser | None:
    """Returns the appropriate tree-sitter Parser for the given file extension."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        return Parser(PY_LANGUAGE)
    elif suffix in (".js", ".jsx", ".mjs", ".cjs"):
        return Parser(JS_LANGUAGE)
    elif suffix == ".ts":
        return Parser(TS_LANGUAGE)
    elif suffix == ".tsx":
        return Parser(TSX_LANGUAGE)
    return None


def _calculate_complexity_python(node: Node) -> int:
    """
    Calculates cyclomatic complexity for a Python function/method AST.
    Base complexity is 1. Increments for every decision/branch point.
    """
    complexity = 1
    branch_types = {
        "if_statement",
        "elif_clause",
        "for_statement",
        "while_statement",
        "except_clause",
        "conditional_expression",
        "assert_statement",
    }

    def walk(n: Node) -> None:
        nonlocal complexity
        if n.type in branch_types:
            complexity += 1
        elif n.type == "boolean_operator":
            # Each 'and' or 'or' introduces an alternative execution path
            complexity += 1
        for child in n.children:
            walk(child)

    walk(node)
    return complexity


def _calculate_complexity_js(node: Node) -> int:
    """Calculates cyclomatic complexity for a JS/TS function/method AST."""
    complexity = 1
    branch_types = {
        "if_statement",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "catch_clause",
        "ternary_expression",
    }

    def walk(n: Node) -> None:
        nonlocal complexity
        if n.type in branch_types:
            complexity += 1
        elif n.type == "binary_expression":
            op_node = n.child_by_field_name("operator")
            if op_node and op_node.text in (b"&&", b"||", b"??"):
                complexity += 1
        for child in n.children:
            walk(child)

    walk(node)
    return complexity


def _extract_docstring_python(body_node: Node, source_bytes: bytes) -> str | None:
    """Extracts docstring from the first statement of a Python body if present."""
    if not body_node:
        return None
    for child in body_node.children:
        if child.type == "comment":
            continue
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type in ("string", "concatenated_string"):
                    raw = source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="replace")
                    clean = raw.strip()
                    for quote in ('"""', "'''", '"', "'"):
                        if clean.startswith(quote) and clean.endswith(quote) and len(clean) >= 2 * len(quote):
                            clean = clean[len(quote):-len(quote)].strip()
                            break
                    return clean if clean else None
        break
    return None


class CodeASTExtractor:
    """Extracts symbols, calls, imports, and metadata from Python and JS/TS ASTs."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()

    def _rel_path(self, path: Path) -> str:
        """Returns normalized POSIX relative path from root directory."""
        try:
            return path.resolve().relative_to(self.root_dir).as_posix()
        except ValueError:
            return path.as_posix()

    def extract_all(self) -> list[SymbolNode]:
        """Scans root_dir and extracts all symbols from all discoverable source files."""
        files = scan_source_files(self.root_dir)
        nodes: list[SymbolNode] = []
        for f in files:
            nodes.extend(self.extract_file(f))
        return nodes

    def extract_file(self, file_path: Path) -> list[SymbolNode]:
        """Parses a single file and extracts its symbol nodes."""
        parser = _get_parser_for_file(file_path)
        if not parser:
            return []

        try:
            source_bytes = file_path.read_bytes()
        except Exception:
            return []

        tree = parser.parse(source_bytes)
        rel_path = self._rel_path(file_path)

        # Create the top-level File Node
        line_count = len(source_bytes.splitlines()) or 1
        file_node = SymbolNode(
            id=rel_path,
            label=file_path.name,
            node_type="file",
            source_file=rel_path,
            line_start=1,
            line_end=line_count,
            body_source=source_bytes.decode("utf-8", errors="replace"),
        )

        nodes: list[SymbolNode] = [file_node]

        if file_path.suffix.lower() == ".py":
            self._extract_python_symbols(tree.root_node, source_bytes, rel_path, file_node, nodes)
        else:
            self._extract_js_symbols(tree.root_node, source_bytes, rel_path, file_node, nodes)

        return nodes

    def _extract_python_symbols(
        self,
        root: Node,
        source: bytes,
        rel_path: str,
        file_node: SymbolNode,
        out_nodes: list[SymbolNode],
    ) -> None:
        """Walks Python AST extracting imports, classes, functions, and methods."""
        # First collect file-level imports
        file_imports: list[dict[str, Any]] = []

        def collect_imports(n: Node) -> None:
            if n.type == "import_statement":
                # import x, y as z
                for child in n.children:
                    if child.type == "dotted_name":
                        mod = source[child.start_byte:child.end_byte].decode("utf-8")
                        file_imports.append({"module": mod, "name": mod, "alias": None, "line": n.start_point[0] + 1})
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        alias_node = child.child_by_field_name("alias")
                        if name_node and alias_node:
                            mod = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                            alias = source[alias_node.start_byte:alias_node.end_byte].decode("utf-8")
                            file_imports.append({"module": mod, "name": mod, "alias": alias, "line": n.start_point[0] + 1})
            elif n.type == "import_from_statement":
                # from x import y as z
                mod_node = n.child_by_field_name("module_name")
                module_name = source[mod_node.start_byte:mod_node.end_byte].decode("utf-8") if mod_node else ""
                for child in n.children:
                    if child.type == "dotted_name" and child != mod_node:
                        sym_name = source[child.start_byte:child.end_byte].decode("utf-8")
                        file_imports.append({"module": module_name, "name": sym_name, "alias": None, "line": n.start_point[0] + 1})
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        alias_node = child.child_by_field_name("alias")
                        if name_node and alias_node:
                            sym_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                            alias = source[alias_node.start_byte:alias_node.end_byte].decode("utf-8")
                            file_imports.append({"module": module_name, "name": sym_name, "alias": alias, "line": n.start_point[0] + 1})

        for child in root.children:
            collect_imports(child)
        file_node.imports = file_imports

        # Next walk declarations (functions, classes, methods)
        def walk_declarations(n: Node, parent_symbol: str | None = None, parent_id: str | None = None) -> None:
            # Check for decorated definitions
            decorators: list[str] = []
            target_def: Node = n

            if n.type == "decorated_definition":
                for child in n.children:
                    if child.type == "decorator":
                        dec_text = source[child.start_byte:child.end_byte].decode("utf-8").strip()
                        decorators.append(dec_text)
                    elif child.type in ("function_definition", "class_definition"):
                        target_def = child

            if target_def.type == "function_definition":
                name_node = target_def.child_by_field_name("name")
                if not name_node:
                    return
                func_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")

                # Line range & body
                line_start = target_def.start_point[0] + 1
                line_end = target_def.end_point[0] + 1
                body_node = target_def.child_by_field_name("body")
                body_source = source[target_def.start_byte:target_def.end_byte].decode("utf-8")

                # Parameters
                params: list[str] = []
                params_node = target_def.child_by_field_name("parameters")
                if params_node:
                    for p in params_node.children:
                        if p.type in ("identifier", "typed_parameter", "default_parameter", "typed_default_parameter"):
                            p_name_node = p.child_by_field_name("name") or (p if p.type == "identifier" else None)
                            if p_name_node:
                                params.append(source[p_name_node.start_byte:p_name_node.end_byte].decode("utf-8"))

                # Return type
                ret_node = target_def.child_by_field_name("return_type")
                ret_type = source[ret_node.start_byte:ret_node.end_byte].decode("utf-8").strip() if ret_node else None

                # Docstring & complexity
                docstring = _extract_docstring_python(body_node, source) if body_node else None
                complexity = _calculate_complexity_python(target_def)

                # Calls made inside function
                calls = self._extract_python_calls(target_def, source)

                is_method = parent_symbol is not None
                scoped_name = f"{parent_symbol}::{func_name}" if parent_symbol else func_name
                node_id = f"{rel_path}::{scoped_name}"

                sym_node = SymbolNode(
                    id=node_id,
                    label=func_name,
                    node_type="method" if is_method else "function",
                    source_file=rel_path,
                    line_start=line_start,
                    line_end=line_end,
                    docstring=docstring,
                    parameters=params,
                    return_type=ret_type,
                    cyclomatic_complexity=complexity,
                    calls=calls,
                    decorators=decorators,
                    parent_id=parent_id or file_node.id,
                    body_source=body_source,
                )
                out_nodes.append(sym_node)

            elif target_def.type == "class_definition":
                name_node = target_def.child_by_field_name("name")
                if not name_node:
                    return
                class_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")

                line_start = target_def.start_point[0] + 1
                line_end = target_def.end_point[0] + 1
                body_node = target_def.child_by_field_name("body")
                body_source = source[target_def.start_byte:target_def.end_byte].decode("utf-8")

                # Docstring
                docstring = _extract_docstring_python(body_node, source) if body_node else None

                node_id = f"{rel_path}::{class_name}"
                class_node = SymbolNode(
                    id=node_id,
                    label=class_name,
                    node_type="class",
                    source_file=rel_path,
                    line_start=line_start,
                    line_end=line_end,
                    docstring=docstring,
                    decorators=decorators,
                    parent_id=file_node.id,
                    body_source=body_source,
                )
                out_nodes.append(class_node)

                # Traverse methods within the class
                if body_node:
                    for child in body_node.children:
                        walk_declarations(child, parent_symbol=class_name, parent_id=node_id)

        for child in root.children:
            walk_declarations(child)

    def _extract_python_calls(self, node: Node, source: bytes) -> list[str]:
        """Extracts unique function/method call identifiers from a Python node."""
        calls: list[str] = []
        seen: set[str] = set()

        def walk(n: Node) -> None:
            if n.type == "call":
                func_node = n.child_by_field_name("function")
                if func_node:
                    call_name: str | None = None
                    if func_node.type == "identifier":
                        call_name = source[func_node.start_byte:func_node.end_byte].decode("utf-8")
                    elif func_node.type == "attribute":
                        attr_node = func_node.child_by_field_name("attribute")
                        if attr_node:
                            call_name = source[attr_node.start_byte:attr_node.end_byte].decode("utf-8")

                    if call_name and call_name not in BUILTIN_CALL_FILTER and call_name not in seen:
                        seen.add(call_name)
                        calls.append(call_name)

            for child in n.children:
                walk(child)

        walk(node)
        return calls

    def _extract_js_symbols(
        self,
        root: Node,
        source: bytes,
        rel_path: str,
        file_node: SymbolNode,
        out_nodes: list[SymbolNode],
    ) -> None:
        """Walks JavaScript/TypeScript AST extracting imports, classes, and functions."""
        file_imports: list[dict[str, Any]] = []

        def collect_imports(n: Node) -> None:
            if n.type == "import_statement":
                # import { x as y } from 'z' or import x from 'z'
                source_node = n.child_by_field_name("source")
                mod_name = source[source_node.start_byte:source_node.end_byte].decode("utf-8").strip("\"'") if source_node else ""
                file_imports.append({"module": mod_name, "name": mod_name, "alias": None, "line": n.start_point[0] + 1})

        for child in root.children:
            collect_imports(child)
        file_node.imports = file_imports

        def walk_declarations(n: Node, parent_symbol: str | None = None, parent_id: str | None = None) -> None:
            # Handle export statement wrapper
            target_node = n
            if n.type == "export_statement":
                decl = n.child_by_field_name("declaration")
                if decl:
                    target_node = decl

            if target_node.type in ("function_declaration", "generator_function_declaration"):
                name_node = target_node.child_by_field_name("name")
                if not name_node:
                    return
                func_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                line_start = target_node.start_point[0] + 1
                line_end = target_node.end_point[0] + 1
                complexity = _calculate_complexity_js(target_node)
                calls = self._extract_js_calls(target_node, source)

                scoped_name = f"{parent_symbol}::{func_name}" if parent_symbol else func_name
                node_id = f"{rel_path}::{scoped_name}"

                sym_node = SymbolNode(
                    id=node_id,
                    label=func_name,
                    node_type="method" if parent_symbol else "function",
                    source_file=rel_path,
                    line_start=line_start,
                    line_end=line_end,
                    cyclomatic_complexity=complexity,
                    calls=calls,
                    parent_id=parent_id or file_node.id,
                    body_source=source[target_node.start_byte:target_node.end_byte].decode("utf-8"),
                )
                out_nodes.append(sym_node)

            elif target_node.type == "class_declaration":
                name_node = target_node.child_by_field_name("name")
                if not name_node:
                    return
                class_name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                line_start = target_node.start_point[0] + 1
                line_end = target_node.end_point[0] + 1

                node_id = f"{rel_path}::{class_name}"
                class_node = SymbolNode(
                    id=node_id,
                    label=class_name,
                    node_type="class",
                    source_file=rel_path,
                    line_start=line_start,
                    line_end=line_end,
                    parent_id=file_node.id,
                    body_source=source[target_node.start_byte:target_node.end_byte].decode("utf-8"),
                )
                out_nodes.append(class_node)

                body_node = target_node.child_by_field_name("body")
                if body_node:
                    for child in body_node.children:
                        if child.type == "method_definition":
                            m_name_node = child.child_by_field_name("name")
                            if m_name_node:
                                m_name = source[m_name_node.start_byte:m_name_node.end_byte].decode("utf-8")
                                m_complexity = _calculate_complexity_js(child)
                                m_calls = self._extract_js_calls(child, source)
                                m_id = f"{rel_path}::{class_name}::{m_name}"
                                out_nodes.append(SymbolNode(
                                    id=m_id,
                                    label=m_name,
                                    node_type="method",
                                    source_file=rel_path,
                                    line_start=child.start_point[0] + 1,
                                    line_end=child.end_point[0] + 1,
                                    cyclomatic_complexity=m_complexity,
                                    calls=m_calls,
                                    parent_id=node_id,
                                    body_source=source[child.start_byte:child.end_byte].decode("utf-8"),
                                ))

        for child in root.children:
            walk_declarations(child)

    def _extract_js_calls(self, node: Node, source: bytes) -> list[str]:
        """Extracts unique function/method call names from a JS/TS node."""
        calls: list[str] = []
        seen: set[str] = set()

        def walk(n: Node) -> None:
            if n.type == "call_expression":
                func_node = n.child_by_field_name("function")
                if func_node:
                    call_name: str | None = None
                    if func_node.type == "identifier":
                        call_name = source[func_node.start_byte:func_node.end_byte].decode("utf-8")
                    elif func_node.type == "member_expression":
                        prop_node = func_node.child_by_field_name("property")
                        if prop_node:
                            call_name = source[prop_node.start_byte:prop_node.end_byte].decode("utf-8")

                    if call_name and call_name not in BUILTIN_CALL_FILTER and call_name not in seen:
                        seen.add(call_name)
                        calls.append(call_name)

            for child in n.children:
                walk(child)

        walk(node)
        return calls
