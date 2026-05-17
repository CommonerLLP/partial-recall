"""Tests for the search orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.index.pipeline import run_indexing
from partial_recall.search.orchestrator import SearchResult, search
from partial_recall.store.vector_store import VectorStore

# Reuse the FakeEmbeddingProvider from test_pipeline for deterministic embeddings
from tests.test_pipeline import FakeEmbeddingProvider


@pytest.fixture
def indexed_store(tmp_path: Path, fixtures_dir: Path):
    """Build a fresh vector store, populate via run_indexing on the Zotero fixture."""
    adapter = ZoteroAdapter(
        sqlite_path=fixtures_dir / "zotero_snapshot" / "zotero.sqlite",
        storage_path=fixtures_dir / "zotero_snapshot" / "storage",
    )
    store = VectorStore(tmp_path / "vectors.sqlite")
    provider = FakeEmbeddingProvider()
    run_indexing(adapter=adapter, store=store, provider=provider)
    yield store, provider
    adapter.close()
    store.close()


def test_search_returns_results(indexed_store) -> None:
    store, provider = indexed_store
    results = search(store=store, provider=provider, query="library policy India", top_k=10)
    assert isinstance(results, list)
    assert len(results) > 0
    assert all(isinstance(r, SearchResult) for r in results)


def test_search_results_have_item_metadata(indexed_store) -> None:
    store, provider = indexed_store
    results = search(store=store, provider=provider, query="library", top_k=5)
    for r in results:
        assert r.item_key
        assert r.corpus == "zotero"
        # title / source_type / score should be populated
        assert isinstance(r.score, float)


def test_search_top_k_is_respected(indexed_store) -> None:
    store, provider = indexed_store
    results = search(store=store, provider=provider, query="library", top_k=2)
    assert len(results) <= 2


def test_search_with_no_active_run_raises(tmp_path: Path) -> None:
    """A fresh store with no embedding_runs should fail clearly."""
    from partial_recall.errors import IndexNotReadyError

    store = VectorStore(tmp_path / "vectors.sqlite")
    provider = FakeEmbeddingProvider()
    with pytest.raises(IndexNotReadyError):
        search(store=store, provider=provider, query="anything")
    store.close()
