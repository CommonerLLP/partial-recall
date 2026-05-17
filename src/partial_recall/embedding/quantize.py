"""int8 quantization helpers.

Convention: normalize to unit L2, multiply by 127, round, clip to [-128, 127].
Pack to bytes as raw int8 (1 byte per dimension).
"""

from __future__ import annotations

import numpy as np


def quantize_to_int8(vector: np.ndarray) -> np.ndarray:
    """Quantize a float vector to int8.

    Assumes input is already L2-normalized (the embedding provider normalizes).
    """
    if not np.any(vector):
        return np.zeros(vector.shape, dtype=np.int8)
    scaled = np.clip(np.round(vector * 127.0), -128, 127)
    return scaled.astype(np.int8)


def pack_int8(vector: np.ndarray) -> bytes:
    """Pack an int8 numpy array to bytes."""
    if vector.dtype != np.int8:
        raise ValueError(f"expected int8 dtype; got {vector.dtype}")
    return vector.tobytes()


def unpack_int8(blob: bytes) -> np.ndarray:
    """Unpack bytes to an int8 numpy array."""
    return np.frombuffer(blob, dtype=np.int8)
