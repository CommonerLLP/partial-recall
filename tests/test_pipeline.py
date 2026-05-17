"""Tests for the indexing pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.corpus.types import ItemKind
from partial_recall.embedding.quantize import pack_int8
from partial_recall.embedding.types import (
    DistanceMetric,
    EmbeddingBatch,
    EmbeddingMetadata,
    Quantization,
)
from partial_recall.index.pipeline import IndexResult, run_indexing
from partial_recall.store.vector_store import VectorStore


class FakeEmbeddingProvider:
    """Deterministic toy embedder for tests: hashes text to a 4-dim int8 vector."""

    def __init__(self) -> None:
        self._metadata = EmbeddingMetadata(
            provider="fake-onnx",
            model_name="fake-model",
            model_version="v1",
            dimensions=4,
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
        import numpy as np
        vectors: list[bytes] = []
        for t in texts:
            # Simple deterministic mapping: hash bytes mod 256 - 128 for first 4 dims
            arr = np.array([(hash(t + str(i)) % 256) - 128 for i in range(4)], dtype=np.int8)
            # Make it look L2-normalized-ish (we lie; tests don't depend on real cosine)
            vectors.append(pack_int8(arr))
        return EmbeddingBatch(texts=texts, vectors=vectors, norms=None)

    def close(self) -> None:
        pass


@pytest.fixture
def adapter(fixtures_dir: Path) -> ZoteroAdapter:
    a = ZoteroAdapter(
        sqlite_path=fixtures_dir / "zotero_snapshot" / "zotero.sqlite",
        storage_path=fixtures_dir / "zotero_snapshot" / "storage",
    )
    yield a
    a.close()


@pytest.fixture
def store(tmp_path: Path) -> VectorStore:
    s = VectorStore(tmp_path / "vectors.sqlite")
    yield s
    s.close()


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


def test_pipeline_indexes_two_items_from_fixture(adapter, store, provider) -> None:
    result = run_indexing(adapter=adapter, store=store, provider=provider)
    assert isinstance(result, IndexResult)
    assert result.item_count >= 2  # ITEM01XX, ITEM02XX
    assert result.chunk_count >= 2  # at least one chunk per item


def test_pipeline_creates_an_embedding_run(adapter, store, provider) -> None:
    run_indexing(adapter=adapter, store=store, provider=provider)
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].provider == "fake-onnx"
    assert runs[0].dimensions == 4
    assert runs[0].is_active is True


def test_pipeline_is_idempotent_on_unchanged_corpus(adapter, store, provider) -> None:
    """Running twice yields the same chunk_count; second run skips already-indexed chunks."""
    r1 = run_indexing(adapter=adapter, store=store, provider=provider)
    # Second run creates a NEW embedding_run (since model could differ) but chunks should match.
    # Return value intentionally unused; we inspect the store directly below.
    run_indexing(adapter=adapter, store=store, provider=provider)
    runs = store.list_runs()
    assert len(runs) == 2
    # Chunks created in run 1 are reused (text_hash dedup); run 2 inserts new vectors
    # but chunk count overall stays the same.
    # We verify by counting chunks directly:
    chunk_total = store._conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
    assert chunk_total == r1.chunk_count  # no new chunks in r2
    # Vector count should be 2x (each chunk now has 2 vectors, one per run)
    vec_total = store._conn.execute("SELECT COUNT(*) AS n FROM vectors").fetchone()["n"]
    assert vec_total == r1.chunk_count * 2


def test_pipeline_skips_when_no_items(store, provider, tmp_path) -> None:
    """An empty adapter produces a zero-item, zero-chunk result without crashing."""
    class EmptyAdapter:
        name = "empty"
        version = "0"
        capabilities = frozenset({ItemKind.TEXT, ItemKind.METADATA})
        def list_items(self, since=None):
            return iter([])
        def get_sources(self, item):
            return iter([])
        def get_text(self, item, source):
            return None
        def get_image(self, item, source):
            return None
        def close(self):
            pass

    result = run_indexing(adapter=EmptyAdapter(), store=store, provider=provider)
    assert result.item_count == 0
    assert result.chunk_count == 0
