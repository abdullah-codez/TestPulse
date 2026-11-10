"""
TestPulse — Remote API Embedder
Produces dense vector embeddings strictly via remote API endpoints (LiteLLM / OpenRouter / OpenAI).
Zero local PyTorch, SentenceTransformers, or HuggingFace models loaded, preserving the 16GB host RAM limit.
"""

from __future__ import annotations

import os
from typing import Any

import litellm

from testpulse.core.config import settings


def get_embeddings(
    texts: list[str],
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    batch_size: int | None = None,
) -> list[list[float]]:
    """
    Computes vector embeddings for a batch of strings using remote API.
    Splits into sub-batches according to settings.embedding_batch_size.
    """
    if not texts:
        return []

    target_model = model or settings.embedding_model
    target_api_key = (
        api_key
        or settings.embedding_api_key
        or settings.openrouter_api_key
        or os.environ.get("OPENROUTER_API_KEY", "")
    )
    target_base_url = base_url or settings.embedding_base_url
    target_batch_size = max(1, batch_size or settings.embedding_batch_size or 32)

    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), target_batch_size):
        batch = texts[i : i + target_batch_size]
        kwargs: dict[str, Any] = {
            "model": target_model,
            "input": batch,
        }
        if target_api_key:
            kwargs["api_key"] = target_api_key
        if target_base_url:
            kwargs["api_base"] = target_base_url

        try:
            response: Any = litellm.embedding(**kwargs)
            batch_vectors: list[list[float]] = []
            for item in response.data:
                if isinstance(item, dict):
                    batch_vectors.append(item["embedding"])
                else:
                    batch_vectors.append(item.embedding)
            all_embeddings.extend(batch_vectors)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to generate embeddings via remote model '{target_model}': {exc}"
            ) from exc

    return all_embeddings


def get_embedding(
    text: str,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[float]:
    """Computes a vector embedding for a single text string."""
    vectors = get_embeddings(
        texts=[text],
        model=model,
        api_key=api_key,
        base_url=base_url,
    )
    if not vectors:
        raise ValueError("Remote embedding endpoint returned empty vector list.")
    return vectors[0]
