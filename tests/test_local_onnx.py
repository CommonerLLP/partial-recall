"""Tests for LocalONNXProvider. Network access required on first run (model download)."""

from __future__ import annotations

import numpy as np
import pytest

from partial_recall.embedding.providers.local_onnx import LocalONNXProvider
from partial_recall.embedding.types import DistanceMetric, Quantization


@pytest.fixture(scope="module")
def provider():
    p = LocalONNXProvider(model_name="intfloat/multilingual-e5-small")
    yield p
    p.close()


@pytest.mark.slow
def test_metadata(provider: LocalONNXProvider) -> None:
    meta = provider.metadata
    assert meta.dimensions == 384
    assert meta.normalized is True
    assert meta.distance_metric == DistanceMetric.COSINE
    assert provider.quantization == Quantization.INT8


@pytest.mark.slow
def test_embed_one_text(provider: LocalONNXProvider) -> None:
    batch = provider.embed(["library policy in India"], task="search_document")
    assert batch.vectors is not None
    assert len(batch.vectors) == 1
    assert len(batch.vectors[0]) == 384


@pytest.mark.slow
def test_embed_empty_list_returns_empty(provider: LocalONNXProvider) -> None:
    batch = provider.embed([], task="search_document")
    assert batch.vectors == []


@pytest.mark.slow
def test_query_and_doc_prefix_differ(provider: LocalONNXProvider) -> None:
    doc_batch = provider.embed(["library policy"], task="search_document")
    query_batch = provider.embed(["library policy"], task="search_query")
    assert doc_batch.vectors[0] != query_batch.vectors[0]


@pytest.mark.slow
def test_multilingual_embedding_distinguishes_languages(provider: LocalONNXProvider) -> None:
    """English vs Hindi both embed without error AND yield distinct vectors."""
    batch = provider.embed(["library", "पुस्तकालय"], task="search_document")
    assert len(batch.vectors) == 2
    v0 = np.frombuffer(batch.vectors[0], dtype=np.int8).astype(np.int32)
    v1 = np.frombuffer(batch.vectors[1], dtype=np.int8).astype(np.int32)
    assert not np.array_equal(v0, v1)
