"""Tests for the MCP semantic_search tool handler."""

from __future__ import annotations

import json
import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.index.pipeline import run_indexing
from partial_recall.mcp.compat import tool_input_schema
from partial_recall.mcp.tools.semantic_search import (
    SEMANTIC_SEARCH_TOOL,
    handle_semantic_search,
)
from partial_recall.store.vector_store import VectorStore
from tests.test_pipeline import FakeEmbeddingProvider


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _vec(values: list[int]) -> bytes:
    """Pack a list of ints into an int8 vector blob."""
    return struct.pack(f"{len(values)}b", *values)


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


@pytest.fixture
def mixed_corpus_store(tmp_path: Path) -> VectorStore:
    """Store with many zotero chunks scoring near 1.0 and one folder chunk
    scoring slightly lower — so the folder item is crowded out of any
    fixed global top_k window when both corpora are scanned together."""
    store = VectorStore(tmp_path / "vectors.sqlite")
    run_id = store.create_run(
        provider="fake", model_name="fake", model_version="v1",
        dimensions=4, quantization="int8", normalized=True,
        distance_metric="cosine", chunker_name="char", chunker_version="v1",
        started_at=_now(),
    )
    store.activate_run(run_id)

    # Insert 10 zotero items, each with 1 chunk scoring ~1.0 (vector [127,0,0,0])
    for i in range(10):
        key = f"ZOT{i:03d}"
        store.upsert_item(
            item_key=key, corpus="zotero", item_type="journalArticle",
            title=f"Zotero item {i}", date=None, creators_json="[]",
            abstract=None, metadata_hash=f"hz{i}", last_indexed_at=_now(),
            corpus_ref=None,
        )
        cid = store.insert_chunk(
            item_key=key, corpus="zotero", source_type="pdf", source_ref=None,
            chunk_index=0, char_offset_start=0, char_offset_end=100,
            text_hash=f"tz{i}", text_preview=f"zotero chunk {i}",
            chunker_version="v1", detected_locale=None, indexed_at=_now(),
        )
        store.insert_vector(
            chunk_id=cid, run_id=run_id,
            vector=_vec([127, 0, 0, 0]),
            norm=None, indexed_at=_now(),
        )

    # Insert 1 folder item with a chunk scoring slightly below the zotero ones
    store.upsert_item(
        item_key="FOL001", corpus="folder", item_type="document",
        title="Folder item", date=None, creators_json="[]",
        abstract=None, metadata_hash="hf1", last_indexed_at=_now(),
        corpus_ref=None,
    )
    cid_folder = store.insert_chunk(
        item_key="FOL001", corpus="folder", source_type="pdf", source_ref=None,
        chunk_index=0, char_offset_start=0, char_offset_end=100,
        text_hash="tf1", text_preview="folder chunk",
        chunker_version="v1", detected_locale=None, indexed_at=_now(),
    )
    store.insert_vector(
        chunk_id=cid_folder, run_id=run_id,
        vector=_vec([120, 0, 0, 0]),  # slightly lower dot product than zotero chunks
        norm=None, indexed_at=_now(),
    )

    yield store
    store.close()


def test_tool_schema_has_required_fields() -> None:
    schema = tool_input_schema(SEMANTIC_SEARCH_TOOL)
    assert "properties" in schema
    assert "query" in schema["properties"]
    assert "query" in schema.get("required", [])


def test_corpus_filter_accepts_any_corpus_name() -> None:
    """The corpus filter must not carry a closed enum: external adapters
    register corpora (e.g. via dotted-path registry entries) whose names a
    hardcoded list can never anticipate, and the live DB already holds
    corpora outside the built-in adapter set."""
    schema = tool_input_schema(SEMANTIC_SEARCH_TOOL)
    assert "enum" not in schema["properties"]["corpus"]


@pytest.mark.asyncio
async def test_handle_filters_by_external_corpus_name(tmp_path: Path) -> None:
    """A corpus indexed under a non-built-in name is searchable via the
    corpus filter end-to-end."""
    store = VectorStore(tmp_path / "vectors.sqlite")
    run_id = store.create_run(
        provider="fake", model_name="fake", model_version="v1",
        dimensions=4, quantization="int8", normalized=True,
        distance_metric="cosine", chunker_name="char", chunker_version="v1",
        started_at=_now(),
    )
    store.activate_run(run_id)
    store.upsert_item(
        item_key="GN001", corpus="gujarat_news", item_type="article",
        title="Gujarat news item", date=None, creators_json="[]",
        abstract=None, metadata_hash="hg1", last_indexed_at=_now(),
        corpus_ref=None,
    )
    cid = store.insert_chunk(
        item_key="GN001", corpus="gujarat_news", source_type="pdf",
        source_ref=None, chunk_index=0, char_offset_start=0,
        char_offset_end=100, text_hash="tg1", text_preview="gujarat chunk",
        chunker_version="v1", detected_locale=None, indexed_at=_now(),
    )
    store.insert_vector(
        chunk_id=cid, run_id=run_id,
        vector=_vec([127, 0, 0, 0]), norm=None, indexed_at=_now(),
    )
    result = await handle_semantic_search(
        arguments={"query": "anything", "corpus": "gujarat_news"},
        store=store,
        provider=FakeEmbeddingProvider(),
    )
    parsed = json.loads(result[0].text)
    assert len(parsed["results"]) == 1
    assert parsed["results"][0]["corpus"] == "gujarat_news"
    store.close()


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
async def test_corpus_filter_is_pre_search_not_post_filter(
    mixed_corpus_store: VectorStore,
) -> None:
    """Corpus filter must be applied inside the search, not after global top-k.

    The fixture has 10 zotero chunks all scoring near 1.0 and 1 folder chunk
    scoring slightly lower. With top_k=5, a naive post-filter would return []
    for corpus='folder' because the folder item never makes the global top-5.
    A correct pre-filter returns the folder item.
    """
    provider = FakeEmbeddingProvider()
    result = await handle_semantic_search(
        arguments={"query": "anything", "top_k": 5, "corpus": "folder"},
        store=mixed_corpus_store,
        provider=provider,
    )
    parsed = json.loads(result[0].text)
    assert len(parsed["results"]) == 1
    assert parsed["results"][0]["corpus"] == "folder"
    assert parsed["results"][0]["item_key"] == "FOL001"


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
