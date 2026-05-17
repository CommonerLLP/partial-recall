"""Data types for the embedding provider interface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Quantization(StrEnum):
    INT8 = "int8"
    FLOAT16 = "float16"
    FLOAT32 = "float32"


class DistanceMetric(StrEnum):
    COSINE = "cosine"
    DOT = "dot"
    L2 = "l2"


@dataclass(frozen=True)
class EmbeddingMetadata:
    provider: str
    model_name: str
    model_version: str | None
    dimensions: int
    normalized: bool
    distance_metric: DistanceMetric
    max_input_tokens: int


@dataclass
class EmbeddingBatch:
    texts: list[str]
    vectors: list[bytes] | None = None
    norms: list[float] | None = None
