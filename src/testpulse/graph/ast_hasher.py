"""
TestPulse — AST Body Hasher
Calculates deterministic SHA-256 hashes for function, method, and class bodies,
normalizing whitespace and stripping comments and docstrings.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from testpulse.graph.ast_extractor import SymbolNode

# Regex pattern to match triple-quoted docstrings at statement level
_DOCSTRING_PATTERN = re.compile(
    r'^\s*(?:[rRuUbB]{0,2})("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')\s*$',
    re.MULTILINE,
)

# Regex pattern for full-line comments
_LINE_COMMENT_PATTERN = re.compile(r"^\s*(?:#|//).*$", re.MULTILINE)

# Regex pattern for inline comments (# ... or // ...)
_INLINE_COMMENT_PATTERN = re.compile(r"(?<!['\"])(?:#|//).*$")


def normalize_code_body(raw_code: str) -> str:
    """
    Normalizes a code block by:
    1. Removing standalone docstrings.
    2. Removing line and inline comments.
    3. Normalizing whitespace (trimming lines, collapsing blank lines).
    """
    if not raw_code:
        return ""

    # Strip docstrings
    cleaned = _DOCSTRING_PATTERN.sub("", raw_code)

    # Strip line comments
    cleaned = _LINE_COMMENT_PATTERN.sub("", cleaned)

    # Process line-by-line for inline comments and whitespace
    normalized_lines: list[str] = []
    for line in cleaned.splitlines():
        # Strip trailing inline comment if safe
        stripped_line = _INLINE_COMMENT_PATTERN.sub("", line).rstrip()
        # Only retain non-empty lines
        if stripped_line.strip():
            normalized_lines.append(stripped_line.strip())

    return "\n".join(normalized_lines)


def calculate_ast_body_hash(raw_code: str, language: str = "python") -> str:
    """
    Computes a deterministic SHA-256 hash of the normalized code body.
    Internal logic edits (operators, variables, constants) alter the hash,
    while comments and docstring edits do not.
    """
    normalized = normalize_code_body(raw_code)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_hashes_for_nodes(nodes: list[SymbolNode]) -> dict[str, str]:
    """
    Computes a mapping of node_id -> sha256_hash for all callable and class nodes.
    File nodes are hashed using their full normalized content.
    """
    hashes: dict[str, str] = {}
    for node in nodes:
        if node.body_source:
            hashes[node.id] = calculate_ast_body_hash(node.body_source)
    return hashes
