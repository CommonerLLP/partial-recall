"""Tests for int8 vector packing / unpacking."""

from __future__ import annotations

import numpy as np

from partial_recall.embedding.quantize import (
    pack_int8,
    quantize_to_int8,
    unpack_int8,
)


def test_pack_unpack_roundtrip() -> None:
    raw = np.array([0, 1, -1, 127, -128, 50], dtype=np.int8)
    packed = pack_int8(raw)
    unpacked = unpack_int8(packed)
    assert list(unpacked) == list(raw)


def test_quantize_normalized_float_vector_preserves_direction() -> None:
    f = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)
    f = f / np.linalg.norm(f)
    q = quantize_to_int8(f)
    approx = q.astype(np.float32) / 127.0
    cosine = float(np.dot(f, approx) / (np.linalg.norm(f) * np.linalg.norm(approx)))
    assert cosine > 0.999


def test_quantize_zero_vector_returns_zeros() -> None:
    f = np.zeros(8, dtype=np.float32)
    q = quantize_to_int8(f)
    assert list(q) == [0] * 8


def test_quantize_clips_to_int8_range() -> None:
    f = np.array([100.0, -100.0, 0.5], dtype=np.float32)
    q = quantize_to_int8(f)
    assert q.min() >= -128
    assert q.max() <= 127
