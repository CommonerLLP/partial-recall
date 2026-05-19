"""Tests for the MCP search_fulltext tool (v0.2.4 C2)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.mcp.tools.search_fulltext import (
    SEARCH_FULLTEXT_TOOL,
    handle_search_fulltext,
)
from partial_recall.store.vector_store import VectorStore


@pytest.fixture
def seeded_store(tmp_path: Path) -> Iterator[VectorStore]:
    """A store with three chunks across two corpora, suitable for FTS5
    queries — phrase, OR, NOT, prefix, corpus filter."""
    store = VectorStore(tmp_path / "vectors.sqlite")
    conn = store._conn
    conn.execute(
        "INSERT INTO items (item_key, corpus, item_type, metadata_hash, "
        "last_indexed_at, title, date) VALUES "
        "('I1', 'zotero', 'book', 'h1', '2026-05-19', "
        "'Caste, Race, and the Politics of Memory', '2020-01-15')"
    )
    conn.execute(
        "INSERT INTO items (item_key, corpus, item_type, metadata_hash, "
        "last_indexed_at, title, date) VALUES "
        "('I2', 'folder', 'file', 'h2', '2026-05-19', "
        "'Subaltern Historiography Notes', '2024-03-01')"
    )
    conn.execute(
        "INSERT INTO chunks (item_key, corpus, source_type, source_ref, "
        "chunk_index, text_hash, text_preview, chunker_version, indexed_at) "
        "VALUES ('I1', 'zotero', 'abstract', NULL, 0, 'th1', "
        "'The politics of memory and caste in modern India.', 'cv1', '2026-05-19')"
    )
    conn.execute(
        "INSERT INTO chunks (item_key, corpus, source_type, source_ref, "
        "chunk_index, text_hash, text_preview, chunker_version, indexed_at) "
        "VALUES ('I1', 'zotero', 'note', 'note:N1', 0, 'th2', "
        "'Ambedkar on the village as site of reproduction.', 'cv1', '2026-05-19')"
    )
    conn.execute(
        "INSERT INTO chunks (item_key, corpus, source_type, source_ref, "
        "chunk_index, text_hash, text_preview, chunker_version, indexed_at) "
        "VALUES ('I2', 'folder', 'file', '/tmp/notes.md', 0, 'th3', "
        "'Subaltern studies and historiography of caste oppression.', "
        "'cv1', '2026-05-19')"
    )
    yield store
    store.close()


def test_tool_schema_requires_query() -> None:
    schema = SEARCH_FULLTEXT_TOOL.inputSchema
    assert "query" in schema["properties"]
    assert "query" in schema["required"]
    assert schema["properties"]["query"]["type"] == "string"
    assert "top_k" in schema["properties"]
    assert "corpus" in schema["properties"]


@pytest.mark.asyncio
async def test_keyword_query_returns_hits(seeded_store: VectorStore) -> None:
    result = await handle_search_fulltext(
        {"query": "caste"}, store=seeded_store
    )
    payload = json.loads(result[0].text)
    assert payload["result_count"] >= 2
    previews = [r["text_preview"] for r in payload["results"]]
    assert any("caste" in p.lower() for p in previews)


@pytest.mark.asyncio
async def test_phrase_query(seeded_store: VectorStore) -> None:
    """Quoted phrase matches the exact word order."""
    result = await handle_search_fulltext(
        {"query": '"politics of memory"'}, store=seeded_store
    )
    payload = json.loads(result[0].text)
    assert payload["result_count"] == 1
    assert "politics of memory" in payload["results"][0]["text_preview"].lower()


@pytest.mark.asyncio
async def test_prefix_query(seeded_store: VectorStore) -> None:
    """`subaltern*` matches "subaltern" and "subalterns"."""
    result = await handle_search_fulltext(
        {"query": "subaltern*"}, store=seeded_store
    )
    payload = json.loads(result[0].text)
    assert payload["result_count"] >= 1


@pytest.mark.asyncio
async def test_corpus_filter(seeded_store: VectorStore) -> None:
    result = await handle_search_fulltext(
        {"query": "caste", "corpus": "folder"}, store=seeded_store
    )
    payload = json.loads(result[0].text)
    corpora = {r["corpus"] for r in payload["results"]}
    assert corpora == {"folder"}


@pytest.mark.asyncio
async def test_top_k_clamps_result_count(seeded_store: VectorStore) -> None:
    result = await handle_search_fulltext(
        {"query": "caste", "top_k": 1}, store=seeded_store
    )
    payload = json.loads(result[0].text)
    assert payload["result_count"] == 1
    assert len(payload["results"]) == 1


@pytest.mark.asyncio
async def test_missing_query_returns_error_payload(
    seeded_store: VectorStore,
) -> None:
    result = await handle_search_fulltext({}, store=seeded_store)
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "query" in payload["error"].lower()


@pytest.mark.asyncio
async def test_malformed_fts_query_returns_error_payload(
    seeded_store: VectorStore,
) -> None:
    """An unterminated quoted phrase is malformed; the tool returns
    a structured error, not a propagated exception."""
    result = await handle_search_fulltext(
        {"query": 'unclosed "phrase'}, store=seeded_store
    )
    payload = json.loads(result[0].text)
    assert "error" in payload


@pytest.mark.asyncio
async def test_results_include_item_title_and_date(
    seeded_store: VectorStore,
) -> None:
    result = await handle_search_fulltext(
        {"query": '"politics of memory"'}, store=seeded_store
    )
    payload = json.loads(result[0].text)
    hit = payload["results"][0]
    assert hit["title"] == "Caste, Race, and the Politics of Memory"
    assert hit["date"] == "2020-01-15"
    assert hit["source_type"] == "abstract"


@pytest.mark.asyncio
async def test_results_include_bm25_score(seeded_store: VectorStore) -> None:
    result = await handle_search_fulltext(
        {"query": "caste"}, store=seeded_store
    )
    payload = json.loads(result[0].text)
    for hit in payload["results"]:
        assert "score" in hit
        # bm25 in SQLite FTS5 returns a *negative* number (smaller =
        # more relevant); the tool exposes it raw and orders by it
        # ASC. Any numeric value is acceptable; presence is what
        # matters here.
        assert hit["score"] is None or isinstance(hit["score"], (int, float))
