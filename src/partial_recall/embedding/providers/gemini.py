"""GeminiAPIProvider — Google Gemini embedding API via httpx.

Uses gemini-embedding-001 (3072-dim float32). Quantized to int8 for storage.
API key from PARTIAL_RECALL_GEMINI_API_KEY env var (preferred) or
GEMINI_API_KEY env var (fallback). v0.1.0 will add keyring secret backend.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
import numpy as np

from partial_recall.embedding.quantize import pack_int8, quantize_to_int8
from partial_recall.embedding.types import (
    DistanceMetric,
    EmbeddingBatch,
    EmbeddingMetadata,
    Quantization,
)
from partial_recall.errors import (
    EmbeddingProviderAuthError,
    EmbeddingProviderError,
    EmbeddingProviderNetworkError,
    EmbeddingProviderRateLimitError,
)

_DEFAULT_API_URL = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_MODEL = "gemini-embedding-001"
_DEFAULT_DIMENSIONS = 3072
_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_BATCH_SIZE = 100  # Gemini accepts up to ~100 in batchEmbedContents
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_RETRIES = 5


def _resolve_api_key(explicit: str | None = None) -> str:
    """Resolve the Gemini API key.

    Order:
        1. explicit constructor argument
        2. PARTIAL_RECALL_GEMINI_API_KEY env var
        3. GEMINI_API_KEY env var
    """
    if explicit:
        return explicit
    for var in ("PARTIAL_RECALL_GEMINI_API_KEY", "GEMINI_API_KEY"):
        v = os.environ.get(var)
        if v:
            return v
    raise EmbeddingProviderAuthError(
        "No Gemini API key found. Set PARTIAL_RECALL_GEMINI_API_KEY (or GEMINI_API_KEY) "
        "in your environment, or pass api_key= to GeminiAPIProvider()."
    )


class GeminiAPIProvider:
    """Google Gemini embedding API provider."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_API_URL,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        http_client: httpx.Client | None = None,
    ):
        self._api_key = _resolve_api_key(api_key)
        self.model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._client = http_client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = http_client is None
        self._metadata = EmbeddingMetadata(
            provider="gemini",
            model_name=model_name,
            model_version=None,
            dimensions=_DEFAULT_DIMENSIONS,
            normalized=True,
            distance_metric=DistanceMetric.COSINE,
            max_input_tokens=_DEFAULT_MAX_TOKENS,
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
        task_type = "RETRIEVAL_QUERY" if task == "search_query" else "RETRIEVAL_DOCUMENT"
        all_packed: list[bytes] = []
        for i in range(0, len(texts), bs):
            chunk = texts[i : i + bs]
            response_vectors = self._batch_embed(chunk, task_type=task_type)
            for raw in response_vectors:
                vec = np.array(raw, dtype=np.float32)
                # L2 normalize (Gemini doesn't guarantee unit norm).
                n = float(np.linalg.norm(vec))
                if n > 0:
                    vec = vec / n
                q = quantize_to_int8(vec)
                all_packed.append(pack_int8(q))
        return EmbeddingBatch(texts=texts, vectors=all_packed, norms=None)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _batch_embed(
        self, texts: list[str], task_type: str
    ) -> list[list[float]]:
        """Send one batchEmbedContents request, return list-of-vectors."""
        url = f"{self._base_url}/models/{self.model_name}:batchEmbedContents"
        payload: dict[str, Any] = {
            "requests": [
                {
                    "model": f"models/{self.model_name}",
                    "content": {"parts": [{"text": t}]},
                    "taskType": task_type,
                }
                for t in texts
            ]
        }
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        return self._post_with_retry(url, headers=headers, json=payload)

    def _post_with_retry(
        self, url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> list[list[float]]:
        """POST with exponential backoff on 429 / 5xx / network errors."""
        delay = 1.0
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                r = self._client.post(url, headers=headers, json=json)
            except httpx.HTTPError as e:
                last_err = EmbeddingProviderNetworkError(f"Gemini API network error: {e}")
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            if r.status_code in (401, 403):
                raise EmbeddingProviderAuthError(
                    f"Gemini API auth error ({r.status_code}): {r.text[:200]}"
                )
            if r.status_code == 429:
                last_err = EmbeddingProviderRateLimitError(
                    f"Gemini API rate limit (attempt {attempt + 1}/{self._max_retries}): "
                    f"{r.text[:200]}"
                )
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            if r.status_code >= 500:
                last_err = EmbeddingProviderError(
                    f"Gemini API server error {r.status_code}: {r.text[:200]}"
                )
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            if r.status_code != 200:
                raise EmbeddingProviderError(
                    f"Gemini API unexpected status {r.status_code}: {r.text[:200]}"
                )
            # Success.
            data = r.json()
            embeddings = data.get("embeddings", [])
            return [emb["values"] for emb in embeddings]
        # Exhausted retries.
        if last_err:
            raise last_err
        raise EmbeddingProviderError("Gemini API: exhausted retries with no specific error")
