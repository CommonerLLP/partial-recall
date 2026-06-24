"""Tests for SentenceTransformerProvider.

These are unit tests: they inject a tiny fake sentence-transformers module so
normal non-live test runs never fetch Hugging Face model metadata.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from partial_recall.embedding.providers.sentence_transformer import (
    SentenceTransformerProvider,
)
from partial_recall.embedding.quantize import unpack_int8
from partial_recall.embedding.types import DistanceMetric, Quantization


class _FakeSentenceTransformer:
    def __init__(self, model_name: str, device: str) -> None:
        self.model_name = model_name
        self.device = device

    def get_sentence_embedding_dimension(self) -> int:
        return 4

    def encode(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool,
        show_progress_bar: bool,
        convert_to_numpy: bool,
    ) -> np.ndarray:
        assert normalize_embeddings is True
        assert show_progress_bar is False
        assert convert_to_numpy is True
        return np.array([_fake_embedding(text) for text in texts], dtype=np.float32)


def _fake_embedding(text: str) -> np.ndarray:
    lowered = text.lower()
    if "quantum" in lowered or "wave" in lowered:
        return np.array([0.0, 0.0, 0.7071, 0.7071], dtype=np.float32)
    if "caste" in lowered or "discrimination" in lowered:
        return np.array([0.7071, 0.7071, 0.0, 0.0], dtype=np.float32)
    if "rights" in lowered:
        return np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


@pytest.fixture(scope="module")
def fake_sentence_transformers_module() -> types.ModuleType:
    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = _FakeSentenceTransformer
    return module


@pytest.fixture
def provider(
    monkeypatch: pytest.MonkeyPatch,
    fake_sentence_transformers_module: types.ModuleType,
) -> SentenceTransformerProvider:
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        fake_sentence_transformers_module,
    )
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
