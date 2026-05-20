"""Tests for SentenceTransformerProvider.

sentence-transformers is an optional dependency — all tests that need it
are skipped if it is not installed.
"""

from __future__ import annotations

import numpy as np
import pytest

sentence_transformers = pytest.importorskip(
    "sentence_transformers",
    reason="sentence-transformers not installed",
)


from partial_recall.embedding.providers.sentence_transformer import (  # noqa: E402
    SentenceTransformerProvider,
)
from partial_recall.embedding.quantize import unpack_int8  # noqa: E402
from partial_recall.embedding.types import DistanceMetric, Quantization  # noqa: E402


@pytest.fixture(scope="module")
def provider() -> SentenceTransformerProvider:
    # Use the smallest available model to keep tests fast.
    return SentenceTransformerProvider(
        model_name="intfloat/multilingual-e5-small", device="cpu"
    )


def test_metadata_provider_name(provider: SentenceTransformerProvider) -> None:
    assert provider.metadata.provider == "sentence-transformer"


def test_metadata_distance_metric(provider: SentenceTransformerProvider) -> None:
    assert provider.metadata.distance_metric == DistanceMetric.COSINE


def test_quantization_is_int8(provider: SentenceTransformerProvider) -> None:
    assert provider.quantization == Quantization.INT8


def test_embed_returns_correct_count(provider: SentenceTransformerProvider) -> None:
    texts = ["Caste is not a division of labour.", "It is a division of labourers."]
    batch = provider.embed(texts)
    assert len(batch.vectors) == 2


def test_embed_empty_input(provider: SentenceTransformerProvider) -> None:
    batch = provider.embed([])
    assert batch.vectors == []
    assert batch.texts == []


def test_embed_vectors_are_bytes(provider: SentenceTransformerProvider) -> None:
    batch = provider.embed(["The Annihilation of Caste."])
    assert all(isinstance(v, bytes) for v in batch.vectors)


def test_embed_vectors_unpack_to_correct_dim(provider: SentenceTransformerProvider) -> None:
    batch = provider.embed(["Rights are not given, they are taken."])
    dims = provider.metadata.dimensions
    vec = unpack_int8(batch.vectors[0])
    assert vec.shape == (dims,)


def test_embed_single_text(provider: SentenceTransformerProvider) -> None:
    batch = provider.embed(["single"])
    assert len(batch.vectors) == 1


def test_embed_batch_size_one(provider: SentenceTransformerProvider) -> None:
    texts = ["a", "b", "c"]
    batch = provider.embed(texts, batch_size=1)
    assert len(batch.vectors) == 3


def test_similar_texts_closer_than_unrelated(provider: SentenceTransformerProvider) -> None:
    """Cosine similarity sanity: semantically related texts should produce
    vectors that are closer together than unrelated ones."""
    batch = provider.embed([
        "The history of caste in South Asia.",
        "Caste discrimination in India.",
        "Quantum mechanics and wave functions.",
    ])
    def _vec(i: int) -> np.ndarray:
        return unpack_int8(batch.vectors[i]).astype(np.float32)

    v0, v1, v2 = _vec(0), _vec(1), _vec(2)
    cos_related = float(np.dot(v0, v1) / (np.linalg.norm(v0) * np.linalg.norm(v1) + 1e-9))
    cos_unrelated = float(np.dot(v0, v2) / (np.linalg.norm(v0) * np.linalg.norm(v2) + 1e-9))
    assert cos_related > cos_unrelated
