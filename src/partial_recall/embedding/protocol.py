"""EmbeddingProvider Protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from partial_recall.embedding.types import EmbeddingBatch, EmbeddingMetadata, Quantization


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Pluggable embedding provider interface.

    Implementations pack vectors per `self.quantization`. Reader code
    consults `self.metadata.normalized` to decide whether to compute norms.
    """

    @property
    def metadata(self) -> EmbeddingMetadata: ...

    @property
    def quantization(self) -> Quantization: ...

    def embed(
        self,
        texts: list[str],
        task: str = "search_document",
        batch_size: int | None = None,
    ) -> EmbeddingBatch:
        """Embed a list of texts.

        task: 'search_document' for indexing, 'search_query' for queries.
        Some providers (e.g. e5) require asymmetric prefixes.
        """
        ...

    def close(self) -> None:
        """Release model handles or sessions. Idempotent."""
        ...
