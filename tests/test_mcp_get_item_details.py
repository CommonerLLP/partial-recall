"""Tests for the MCP get_item_details tool (v0.2.3 C3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.index.pipeline import run_indexing
from partial_recall.mcp.compat import tool_input_schema
from partial_recall.mcp.tools.get_item_details import (
    GET_ITEM_DETAILS_TOOL,
    handle_get_item_details,
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
    yield store
    adapter.close()
    store.close()


def test_tool_schema_requires_item_key() -> None:
    schema = tool_input_schema(GET_ITEM_DETAILS_TOOL)
    assert "item_key" in schema["properties"]
    assert "item_key" in schema.get("required", [])
    # corpus is optional.
    assert "corpus" not in schema.get("required", [])


@pytest.mark.asyncio
async def test_returns_full_item_metadata(indexed_store) -> None:
    payload = json.loads(
        (await handle_get_item_details(
            {"item_key": "ITEM01XX", "corpus": "zotero"},
            store=indexed_store,
        ))[0].text
    )
    assert "item" in payload
    item = payload["item"]
    assert item["item_key"] == "ITEM01XX"
    assert item["corpus"] == "zotero"
    assert item["title"] == "Library policy in India: a history"
    assert item["date"] == "2020-01-15"
    assert isinstance(item["creators"], list)
    assert any(c.get("last") == "Roy" for c in item["creators"])


@pytest.mark.asyncio
async def test_returns_source_type_breakdown(indexed_store) -> None:
    payload = json.loads(
        (await handle_get_item_details(
            {"item_key": "ITEM01XX"},
            store=indexed_store,
        ))[0].text
    )
    assert "chunks" in payload
    assert "by_source_type" in payload["chunks"]
    # The fixture item has an abstract; at least one source-type entry
    # must show up.
    assert len(payload["chunks"]["by_source_type"]) >= 1
    assert payload["chunks"]["total"] >= 1


@pytest.mark.asyncio
async def test_returns_active_run_vector_count(indexed_store) -> None:
    payload = json.loads(
        (await handle_get_item_details(
            {"item_key": "ITEM01XX"},
            store=indexed_store,
        ))[0].text
    )
    assert payload["active_run"] is not None
    assert "vectors_for_this_item" in payload["active_run"]
    assert payload["active_run"]["vectors_for_this_item"] is not None
    assert payload["active_run"]["vectors_for_this_item"] >= 1


@pytest.mark.asyncio
async def test_missing_item_key_returns_error_payload(indexed_store) -> None:
    result = await handle_get_item_details({}, store=indexed_store)
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "item_key" in payload["error"].lower()


@pytest.mark.asyncio
async def test_nonexistent_item_returns_error_payload(indexed_store) -> None:
    result = await handle_get_item_details(
        {"item_key": "DOES-NOT-EXIST", "corpus": "zotero"},
        store=indexed_store,
    )
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "No item found" in payload["error"]


@pytest.mark.asyncio
async def test_corpus_filter_narrows_search(indexed_store) -> None:
    """When corpus is given, only items in that corpus match."""
    # The fixture has only zotero items; lookup with wrong corpus must
    # return the not-found error rather than returning a zotero item.
    result = await handle_get_item_details(
        {"item_key": "ITEM01XX", "corpus": "folder"},
        store=indexed_store,
    )
    payload = json.loads(result[0].text)
    assert "error" in payload
    assert "folder" in payload["error"]
