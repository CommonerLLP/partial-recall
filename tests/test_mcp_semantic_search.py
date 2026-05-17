"""Tests for the MCP semantic_search tool handler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.index.pipeline import run_indexing
from partial_recall.mcp.tools.semantic_search import (
    SEMANTIC_SEARCH_TOOL,
    handle_semantic_search,
)
from partial_recall.store.vector_store import VectorStore
from tests.test_pipeline import FakeEmbeddingProvider


@pytest.fixture
def indexed_store(tmp_path: Path, fixtures_dir: Path):
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


def test_tool_schema_has_required_fields() -> None:
    schema = SEMANTIC_SEARCH_TOOL.inputSchema
    assert "properties" in schema
    assert "query" in schema["properties"]
    assert "query" in schema.get("required", [])


@pytest.mark.asyncio
async def test_handle_returns_textcontent_with_results(indexed_store) -> None:
    store, provider = indexed_store
    result = await handle_semantic_search(
        arguments={"query": "library policy", "top_k": 5},
        store=store,
        provider=provider,
    )
    assert len(result) == 1
    assert result[0].type == "text"
    parsed = json.loads(result[0].text)
    assert "results" in parsed
    assert "query_metadata" in parsed
    assert len(parsed["results"]) <= 5


@pytest.mark.asyncio
async def test_handle_filters_by_min_score(indexed_store) -> None:
    store, provider = indexed_store
    result = await handle_semantic_search(
        arguments={"query": "library", "top_k": 10, "min_score": 0.99},
        store=store,
        provider=provider,
    )
    parsed = json.loads(result[0].text)
    # With fake embeddings min_score=0.99 will likely filter out everything
    for hit in parsed["results"]:
        assert hit["score"] >= 0.99


@pytest.mark.asyncio
async def test_handle_filters_by_corpus(indexed_store) -> None:
    store, provider = indexed_store
    result = await handle_semantic_search(
        arguments={"query": "library", "top_k": 5, "corpus": "zotero"},
        store=store,
        provider=provider,
    )
    parsed = json.loads(result[0].text)
    for hit in parsed["results"]:
        assert hit["corpus"] == "zotero"


@pytest.mark.asyncio
async def test_handle_no_index_returns_error_payload(tmp_path: Path) -> None:
    """With an empty store (no embedding_run), the handler returns an error
    payload rather than crashing."""
    store = VectorStore(tmp_path / "vectors.sqlite")
    provider = FakeEmbeddingProvider()
    result = await handle_semantic_search(
        arguments={"query": "anything"},
        store=store,
        provider=provider,
    )
    parsed = json.loads(result[0].text)
    assert "error" in parsed or parsed.get("results") == []
    store.close()
