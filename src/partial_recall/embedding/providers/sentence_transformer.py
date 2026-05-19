"""SentenceTransformerProvider — any sentence-transformers model (v0.3.0).

Adds support for multilingual embedding models beyond the default
multilingual-e5-small. Particularly useful for scholars working in
Indic scripts (Urdu, Tamil, Bengali, Malayalam, etc.) where models
specifically trained on those scripts outperform English-centric models.

Recommended models for Indic-language corpora:
  - LaBSE (sentence-transformers/LaBSE): 109 languages including
    Urdu (Arabic script), Tamil, Bengali, Malayalam, Telugu, Kannada.
    768 dimensions. ~550 MB. Runs on 4 GB RAM.
  - MuRIL (google/muril-base-cased): 17 Indian languages + English.
    768 dimensions. ~450 MB.
  - ai4bharat/indic-sentence-bert-nli: Indic-specific, lighter.
  - BAAI/bge-m3: 100+ languages, highest quality; 1024 dimensions,
    ~580 MB int8. Needs 6+ GB RAM.

Configuration example (config.toml):
    [embedding]
    provider = "sentence-transformer"
    model = "sentence-transformers/LaBSE"

Requires the `sentence-transformers` optional dep:
    pipx inject partial-recall sentence-transformers
    OR: pip install 'partial-recall[multilingual]'
"""

from __future__ import annotations

import numpy as np

from partial_recall.embedding.quantize import pack_int8, quantize_to_int8
from partial_recall.embedding.types import (
    DistanceMetric,
    EmbeddingBatch,
    EmbeddingMetadata,
    Quantization,
)
from partial_recall.errors import EmbeddingProviderError

_KNOWN_DIMS: dict[str, int] = {
    "sentence-transformers/LaBSE": 768,
    "google/muril-base-cased": 768,
    "BAAI/bge-m3": 1024,
    "ai4bharat/indic-sentence-bert-nli": 768,
    "intfloat/multilingual-e5-large": 1024,
    "intfloat/multilingual-e5-base": 768,
}

_DEFAULT_DIM = 768


def _resolve_device(device: str) -> str:
    """Resolve 'auto' to the best available device; pass explicit values through.

    Priority: CUDA (NVIDIA GPU) → MPS (Apple Silicon) → CPU.
    'auto' is the default — users with CUDA or Apple Silicon get acceleration
    without any configuration change. Passing 'cpu' explicitly forces CPU.
    """
    if device != "auto":
        return device
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


class SentenceTransformerProvider:
    """Embedding provider backed by any sentence-transformers model.

    Intended for multilingual use cases where the default
    multilingual-e5-small does not cover the target script well.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/LaBSE",
        *,
        batch_size: int = 32,
        device: str = "auto",
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError as e:
            raise EmbeddingProviderError(
                "The `sentence-transformers` package is required for this provider. "
                "Install it with `pipx inject partial-recall sentence-transformers` "
                "or `pip install sentence-transformers`."
            ) from e

        self.model_name = model_name
        self._batch_size = batch_size
        resolved_device = _resolve_device(device)
        self._model = SentenceTransformer(model_name, device=resolved_device)
        dims = (
            self._model.get_sentence_embedding_dimension()
            or _KNOWN_DIMS.get(model_name, _DEFAULT_DIM)
        )
        self._metadata = EmbeddingMetadata(
            provider="sentence-transformer",
            model_name=model_name,
            model_version=None,
            dimensions=dims,
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
        bs = batch_size or self._batch_size
        all_packed: list[bytes] = []
        for i in range(0, len(texts), bs):
            chunk = texts[i : i + bs]
            embeddings = self._model.encode(
                chunk,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            for emb in embeddings:
                q = quantize_to_int8(np.array(emb, dtype=np.float32))
                all_packed.append(pack_int8(q))
        return EmbeddingBatch(texts=texts, vectors=all_packed, norms=None)

    def close(self) -> None:
        self._model = None
