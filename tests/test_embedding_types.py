"""Tests for embedding types and Protocol."""

from __future__ import annotations

from partial_recall.embedding.types import (
    DistanceMetric,
    EmbeddingBatch,
    EmbeddingMetadata,
    Quantization,
)


def test_quantization_enum_values() -> None:
    assert Quantization.INT8.value == "int8"
    assert Quantization.FLOAT16.value == "float16"
    assert Quantization.FLOAT32.value == "float32"


def test_distance_metric_enum_values() -> None:
    assert DistanceMetric.COSINE.value == "cosine"
    assert DistanceMetric.DOT.value == "dot"
    assert DistanceMetric.L2.value == "l2"


def test_embedding_metadata_construction() -> None:
    meta = EmbeddingMetadata(
        provider="local-onnx",
        model_name="intfloat/multilingual-e5-small",
        model_version="v1",
        dimensions=384,
        normalized=True,
        distance_metric=DistanceMetric.COSINE,
        max_input_tokens=512,
    )
    assert meta.dimensions == 384


def test_embedding_batch_starts_with_no_vectors() -> None:
    b = EmbeddingBatch(texts=["a", "b"])
    assert b.vectors is None
