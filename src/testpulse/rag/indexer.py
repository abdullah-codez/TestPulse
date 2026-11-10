"""
TestPulse — Lazy Qdrant Indexer
Indexes AST code and descriptive document chunks into Qdrant Local Mode.
Enforces strict open-and-close lifecycle inside try/finally blocks to prevent database locks.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from testpulse.core.config import settings
from testpulse.rag.embedder import get_embeddings


def index_chunks(
    chunks: list[dict[str, Any]],
    collection_name: str = "testpulse_codebase",
    client_path: str | Path | None = None,
    embedder_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> int:
    """
    Embeds and indexes code/text chunks into a local Qdrant collection.

    CRITICAL FILE LOCK DISCIPLINE:
    Instantiates QdrantClient(path=...), performs the upsert to collection_name,
    and IMMEDIATELY closes the client inside a try/finally block. Never holds
    the client open globally or at FastAPI startup.
    """
    if not chunks:
        return 0

    target_path = Path(client_path or settings.qdrant_path)
    target_path.mkdir(parents=True, exist_ok=True)

    # 1. Generate embeddings using remote embedder
    embed_func = embedder_fn or get_embeddings
    texts = [c["text_content"] for c in chunks]
    embeddings = embed_func(texts)

    if len(embeddings) != len(chunks):
        raise ValueError(
            f"Embedder returned {len(embeddings)} vectors for {len(chunks)} chunks."
        )

    vector_dim = len(embeddings[0]) if embeddings else 1536

    # 2. Strict lazy client open/close lifecycle
    client = QdrantClient(path=str(target_path))
    try:
        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_dim,
                    distance=models.Distance.COSINE,
                ),
            )
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=UserWarning)
                with contextlib.suppress(Exception):
                    client.create_payload_index(
                        collection_name=collection_name,
                        field_name="node_id",
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )

        # 3. Construct PointStructs with deterministic UUID5 identifiers
        points: list[models.PointStruct] = []
        for chunk, vec in zip(chunks, embeddings, strict=True):
            node_id = str(chunk["node_id"])
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, node_id))
            payload = {
                "node_id": node_id,
                "text_content": chunk["text_content"],
                **chunk.get("metadata", {}),
            }
            points.append(models.PointStruct(id=point_id, vector=vec, payload=payload))

        # 4. Perform upsert
        if points:
            client.upsert(collection_name=collection_name, points=points)

        return len(points)
    finally:
        client.close()
