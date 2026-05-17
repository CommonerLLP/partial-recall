"""LocalONNXProvider — multilingual-e5-small via ONNX Runtime.

Downloads model on first use; caches to platformdirs cache dir.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from partial_recall.embedding.quantize import pack_int8, quantize_to_int8
from partial_recall.embedding.types import (
    DistanceMetric,
    EmbeddingBatch,
    EmbeddingMetadata,
    Quantization,
)
from partial_recall.paths import model_cache_dir

_E5_DOC_PREFIX = "passage: "
_E5_QUERY_PREFIX = "query: "

# Filename within the snapshot directory.
_ONNX_FILENAME = "onnx/model.onnx"


class LocalONNXProvider:
    """multilingual-e5-small via ONNX Runtime (CPU)."""

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-small",
        *,
        cache_dir: Path | None = None,
        batch_size: int = 32,
    ):
        from huggingface_hub import snapshot_download
        from onnxruntime import InferenceSession  # type: ignore[import-untyped]
        from tokenizers import Tokenizer

        self.model_name = model_name
        self._batch_size = batch_size
        self._cache_dir = Path(cache_dir) if cache_dir else model_cache_dir()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        snapshot_path = snapshot_download(
            repo_id=model_name,
            cache_dir=str(self._cache_dir),
            allow_patterns=["onnx/*", "tokenizer*", "*.json"],
        )
        self._snapshot_path = Path(snapshot_path)

        onnx_path = self._snapshot_path / _ONNX_FILENAME
        if not onnx_path.exists():
            # Fallback: some snapshots use a flat layout
            onnx_path = self._snapshot_path / "model.onnx"
        if not onnx_path.exists():
            raise FileNotFoundError(f"ONNX model not found in {self._snapshot_path}")

        self._session = InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        tokenizer_path = self._snapshot_path / "tokenizer.json"
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=512)
        self._tokenizer.enable_padding()

        self._metadata = EmbeddingMetadata(
            provider="local-onnx",
            model_name=model_name,
            model_version=None,
            dimensions=384,
            normalized=True,
            distance_metric=DistanceMetric.COSINE,
            max_input_tokens=512,
        )

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    @property
    def quantization(self) -> Quantization:
        return Quantization.INT8

    def embed(
        self,
        texts: list[str],
        task: str = "search_document",
        batch_size: int | None = None,
    ) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch(texts=[], vectors=[], norms=None)
        prefix = _E5_DOC_PREFIX if task == "search_document" else _E5_QUERY_PREFIX
        prefixed = [prefix + t for t in texts]
        bs = batch_size or self._batch_size
        all_packed: list[bytes] = []
        for i in range(0, len(prefixed), bs):
            chunk = prefixed[i : i + bs]
            enc = self._tokenizer.encode_batch(chunk)
            input_ids = np.array([e.ids for e in enc], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            token_type_ids = np.array([e.type_ids for e in enc], dtype=np.int64)
            outputs = self._session.run(
                None,
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "token_type_ids": token_type_ids,
                },
            )
            last_hidden_state = outputs[0]
            embeddings = self._mean_pool(last_hidden_state, attention_mask)
            embeddings = self._l2_normalize(embeddings)
            for emb in embeddings:
                q = quantize_to_int8(emb)
                all_packed.append(pack_int8(q))
        return EmbeddingBatch(texts=texts, vectors=all_packed, norms=None)

    def close(self) -> None:
        self._session = None  # release resources

    @staticmethod
    def _mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
        mask_f = mask.astype(np.float32)[..., None]
        summed = (hidden * mask_f).sum(axis=1)
        counts = mask_f.sum(axis=1).clip(min=1e-9)
        result: np.ndarray = summed / counts
        return result

    @staticmethod
    def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True).clip(min=1e-9)
        result: np.ndarray = vectors / norms
        return result
