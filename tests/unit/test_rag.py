"""
TestPulse — Unit Tests for Milestone 2: Code-Aware RAG with Qdrant Local
Verifies dual-strategy chunking, contextual header injection, remote API embedder,
strict lazy Qdrant client lifecycle, and dual-pipeline retrieval (graph walk + semantic blindspot sweeper).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from qdrant_client import QdrantClient

from testpulse.graph.graph_builder import build_graph
from testpulse.rag.chunker import chunk_markdown_file, chunk_repository
from testpulse.rag.embedder import get_embedding, get_embeddings
from testpulse.rag.indexer import index_chunks
from testpulse.rag.retriever import get_context_for_target

FIXTURE_PATH = Path("tests/fixtures/sample_fastapi").resolve()


def _deterministic_mock_embed(texts: list[str]) -> list[list[float]]:
    """
    Deterministic embedding function for unit tests.
    Generates an 8-dimensional normalized vector where texts containing
    'discount' or '50%' have heavy weight in the first dimension.
    """
    vectors: list[list[float]] = []
    for text in texts:
        t = text.lower()
        vec = [0.0] * 8
        if "discount" in t or "50%" in t:
            vec[0] = 1.0
            vec[1] = 0.5
        elif "order" in t or "customer" in t:
            vec[2] = 1.0
            vec[3] = 0.5
        else:
            # Deterministic hash-based spread
            digest = hashlib.md5(t.encode("utf-8")).digest()
            for idx in range(8):
                vec[idx] = float(digest[idx]) / 255.0

        # Normalize
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        vectors.append(vec)
    return vectors


def _single_mock_embed(text: str) -> list[float]:
    return _deterministic_mock_embed([text])[0]


def test_chunk_repository_ast_and_text() -> None:
    """Verifies that chunk_repository extracts both code AST chunks and descriptive Markdown chunks with headers."""
    G, _ = build_graph(FIXTURE_PATH)
    chunks = chunk_repository(G, workspace_path=FIXTURE_PATH)

    assert len(chunks) > 0

    # 1. Verify Code AST Chunks
    code_chunks = [c for c in chunks if c["metadata"].get("type") == "code"]
    assert len(code_chunks) > 0

    calc_chunk = next(
        (c for c in code_chunks if "calculate_discount" in c["node_id"]),
        None,
    )
    assert calc_chunk is not None
    assert "# [TestPulse cAST Chunk]" in calc_chunk["text_content"]
    assert "# Node ID: services/discount_service.py::DiscountService::calculate_discount" in calc_chunk["text_content"]
    assert "# File: services/discount_service.py (L17-L59)" in calc_chunk["text_content"]
    assert "create_order" in calc_chunk["text_content"]  # Injected Caller
    assert "def calculate_discount" in calc_chunk["text_content"]

    # 2. Verify Descriptive Text Chunks
    text_chunks = [c for c in chunks if c["metadata"].get("type") == "text"]
    assert len(text_chunks) > 0

    readme_rule_chunk = next(
        (c for c in text_chunks if "business-rules" in c["node_id"].lower() or "Business Rules" in c["metadata"].get("section", "")),
        None,
    )
    assert readme_rule_chunk is not None
    assert "# [TestPulse Descriptive Chunk]" in readme_rule_chunk["text_content"]
    assert "# File: README.md" in readme_rule_chunk["text_content"]
    assert "# Section: Business Rules" in readme_rule_chunk["text_content"]
    assert "Discounts cannot exceed 50%" in readme_rule_chunk["text_content"]


def test_chunk_markdown_file_sections(tmp_path: Path) -> None:
    """Verifies markdown semantic section chunking and header injection."""
    md_file = tmp_path / "TEST.md"
    md_file.write_text(
        "# Title\nIntroductory text.\n\n## Section A\nDetail A.\n\n## Section B\nDetail B.",
        encoding="utf-8",
    )
    chunks = chunk_markdown_file(md_file, "TEST.md")

    assert len(chunks) == 3
    assert chunks[0]["metadata"]["section"] == "Title"
    assert chunks[1]["metadata"]["section"] == "Section A"
    assert chunks[2]["metadata"]["section"] == "Section B"
    assert "Detail B." in chunks[2]["text_content"]


@patch("litellm.embedding")
def test_embedder_interface_and_batching(mock_litellm_embedding: MagicMock) -> None:
    """Verifies that remote embedder calls litellm.embedding with batching and does not use local torch models."""
    mock_item1 = MagicMock()
    mock_item1.embedding = [0.1, 0.2, 0.3]
    mock_item2 = MagicMock()
    mock_item2.embedding = [0.4, 0.5, 0.6]
    mock_response = MagicMock()
    mock_response.data = [mock_item1, mock_item2]
    mock_litellm_embedding.return_value = mock_response

    # Test batch embedding
    vectors = get_embeddings(
        texts=["hello world", "test pulse"],
        model="test-embed-model",
        api_key="sk-test-key",
        batch_size=2,
    )

    assert len(vectors) == 2
    assert vectors[0] == [0.1, 0.2, 0.3]
    assert vectors[1] == [0.4, 0.5, 0.6]
    assert mock_litellm_embedding.call_count == 1
    call_kwargs = mock_litellm_embedding.call_args[1]
    assert call_kwargs["model"] == "test-embed-model"
    assert call_kwargs["api_key"] == "sk-test-key"
    assert call_kwargs["input"] == ["hello world", "test pulse"]

    # Test single embedding helper
    mock_response_single = MagicMock()
    mock_response_single.data = [mock_item1]
    mock_litellm_embedding.return_value = mock_response_single

    single_vec = get_embedding("single text", model="test-embed-model", api_key="sk-test")
    assert single_vec == [0.1, 0.2, 0.3]


def test_lazy_qdrant_indexer_and_file_lock_lifecycle(tmp_path: Path) -> None:
    """
    CRITICAL FILE LOCK TEST:
    Verifies that index_chunks opens QdrantClient(path=...), completes upsert,
    and immediately closes the client so that subsequent opens do not fail with lock errors.
    """
    qdrant_dir = tmp_path / "qdrant_db"

    dummy_chunks: list[dict[str, Any]] = [
        {
            "node_id": "test_module::func_a",
            "text_content": "# [TestPulse cAST Chunk]\ndef func_a(): pass",
            "metadata": {"type": "code", "symbol": "func_a"},
        },
        {
            "node_id": "test_module::func_b",
            "text_content": "# [TestPulse cAST Chunk]\ndef func_b(): pass",
            "metadata": {"type": "code", "symbol": "func_b"},
        },
    ]

    # Index chunks via lazy indexer
    count = index_chunks(
        chunks=dummy_chunks,
        collection_name="testpulse_codebase",
        client_path=qdrant_dir,
        embedder_fn=_deterministic_mock_embed,
    )
    assert count == 2

    # Verification: Immediately reopen client from the same directory to confirm lock was released
    verification_client = QdrantClient(path=str(qdrant_dir))
    try:
        assert verification_client.collection_exists("testpulse_codebase")
        info = verification_client.get_collection("testpulse_codebase")
        assert info.points_count == 2
    finally:
        verification_client.close()


def test_dual_pipeline_retriever(tmp_path: Path) -> None:
    """
    Verifies that get_context_for_target pulls both:
    - Pipeline A (Graph Walk): Exact code blocks for target + callers + dependencies
    - Pipeline B (Blindspot Sweeper): Semantic text matches (e.g. README.md business rule)
    """
    G, _ = build_graph(FIXTURE_PATH)
    chunks = chunk_repository(G, workspace_path=FIXTURE_PATH)

    qdrant_dir = tmp_path / "qdrant_retriever"

    # Index repository chunks
    index_chunks(
        chunks=chunks,
        collection_name="testpulse_codebase",
        client_path=qdrant_dir,
        embedder_fn=_deterministic_mock_embed,
    )

    target_node = "services/discount_service.py::DiscountService::calculate_discount"

    # Execute Dual-Pipeline Retrieval
    context = get_context_for_target(
        G=G,
        target_node_id=target_node,
        hop_depth=1,
        collection_name="testpulse_codebase",
        client_path=qdrant_dir,
        embedder_fn=_single_mock_embed,
    )

    assert context != ""
    assert "\n\n---\n\n" in context

    # 1. Pipeline A Checks: Exact target function and calling endpoint
    assert "def calculate_discount" in context
    assert "create_order" in context
    assert "class DiscountService" in context

    # 2. Pipeline B Checks: Semantic match pulled dummy README.md business rule
    assert "Discounts cannot exceed 50%" in context
    assert "# [TestPulse Descriptive Chunk]" in context
    assert "# File: README.md" in context


def test_retriever_shorthand_resolution(tmp_path: Path) -> None:
    """Verifies that get_context_for_target resolves short symbol names to canonical graph node IDs."""
    G, _ = build_graph(FIXTURE_PATH)
    chunks = chunk_repository(G, workspace_path=FIXTURE_PATH)

    qdrant_dir = tmp_path / "qdrant_shorthand"
    index_chunks(
        chunks=chunks,
        collection_name="testpulse_codebase",
        client_path=qdrant_dir,
        embedder_fn=_deterministic_mock_embed,
    )

    # Call with shorthand symbol name
    context = get_context_for_target(
        G=G,
        target_node_id="calculate_discount",
        hop_depth=1,
        collection_name="testpulse_codebase",
        client_path=qdrant_dir,
        embedder_fn=_single_mock_embed,
    )

    assert "def calculate_discount" in context
    assert "Discounts cannot exceed 50%" in context


def test_retriever_nonexistent_collection(tmp_path: Path) -> None:
    """Verifies graceful handling when Qdrant collection does not exist."""
    G, _ = build_graph(FIXTURE_PATH)
    qdrant_dir = tmp_path / "qdrant_empty"

    context = get_context_for_target(
        G=G,
        target_node_id="nonexistent_symbol",
        collection_name="nonexistent_collection",
        client_path=qdrant_dir,
        embedder_fn=_single_mock_embed,
    )
    assert context == ""
