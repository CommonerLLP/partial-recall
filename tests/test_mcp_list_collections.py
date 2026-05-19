"""Tests for the MCP list_collections tool + library-location surface (v0.2.4 C5)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.mcp.tools.get_item_details import handle_get_item_details
from partial_recall.mcp.tools.list_collections import (
    LIST_COLLECTIONS_TOOL,
    handle_list_collections,
)
from partial_recall.store.vector_store import VectorStore


@pytest.fixture
def store_with_collections(tmp_path: Path) -> Iterator[VectorStore]:
    """A store with two collections (one nested) and items linked
    into them, plus library-location fields populated."""
    s = VectorStore(tmp_path / "v.sqlite")
    # Two items, one with full library-location fields
    s.upsert_item(
        item_key="I1", corpus="zotero", item_type="book",
        title="A history of reading", date="2020-01-15",
        creators_json="[]", abstract="A bookish abstract.",
        metadata_hash="h1", last_indexed_at="2026-05-19",
        corpus_ref=None,
        archive="British Library",
        archive_location="Asia Reading Room",
        call_number="X.123/456",
        library_catalog="British Library catalogue",
    )
    s.upsert_item(
        item_key="I2", corpus="zotero", item_type="journalArticle",
        title="On caste and the village", date="2002-03-01",
        creators_json="[]", abstract=None, metadata_hash="h2",
        last_indexed_at="2026-05-19", corpus_ref=None,
    )
    # Collections: a parent "Reading" + child "Caste Studies"
    s.upsert_collection(
        corpus="zotero", collection_key="C1", name="Reading",
        parent_key=None, last_indexed_at="2026-05-19",
    )
    s.upsert_collection(
        corpus="zotero", collection_key="C2", name="Caste Studies",
        parent_key="C1", last_indexed_at="2026-05-19",
    )
    # I1 is in "Reading"; I2 is in "Caste Studies"
    s.link_item_to_collection(corpus="zotero", item_key="I1", collection_key="C1")
    s.link_item_to_collection(corpus="zotero", item_key="I2", collection_key="C2")
    yield s
    s.close()


def test_tool_schema() -> None:
    schema = LIST_COLLECTIONS_TOOL.inputSchema
    assert schema["type"] == "object"
    assert schema["properties"]["corpus"]["default"] == "zotero"


@pytest.mark.asyncio
async def test_list_collections_returns_each_with_item_count(
    store_with_collections: VectorStore,
) -> None:
    result = await handle_list_collections({"corpus": "zotero"},
                                            store=store_with_collections)
    payload = json.loads(result[0].text)
    assert payload["corpus"] == "zotero"
    assert payload["collection_count"] == 2
    by_name = {c["name"]: c for c in payload["collections"]}
    assert "Reading" in by_name
    assert "Caste Studies" in by_name
    assert by_name["Reading"]["item_count"] == 1
    assert by_name["Caste Studies"]["item_count"] == 1
    # Parent reference preserved
    assert by_name["Caste Studies"]["parent_key"] == "C1"
    assert by_name["Reading"]["parent_key"] is None


@pytest.mark.asyncio
async def test_list_collections_defaults_corpus_to_zotero(
    store_with_collections: VectorStore,
) -> None:
    result = await handle_list_collections({}, store=store_with_collections)
    payload = json.loads(result[0].text)
    assert payload["corpus"] == "zotero"
    assert payload["collection_count"] == 2


@pytest.mark.asyncio
async def test_list_collections_empty_for_unknown_corpus(
    store_with_collections: VectorStore,
) -> None:
    result = await handle_list_collections({"corpus": "folder"},
                                            store=store_with_collections)
    payload = json.loads(result[0].text)
    assert payload["collection_count"] == 0
    assert payload["collections"] == []


# ---------------------------------------------------------------------------
# get_item_details surfaces library_location + collections (v0.2.4 C5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_item_details_includes_library_location(
    store_with_collections: VectorStore,
) -> None:
    result = await handle_get_item_details(
        {"item_key": "I1", "corpus": "zotero"},
        store=store_with_collections,
    )
    payload = json.loads(result[0].text)
    loc = payload["item"]["library_location"]
    assert loc["archive"] == "British Library"
    assert loc["archive_location"] == "Asia Reading Room"
    assert loc["call_number"] == "X.123/456"
    assert loc["library_catalog"] == "British Library catalogue"


@pytest.mark.asyncio
async def test_get_item_details_drops_empty_library_location(
    store_with_collections: VectorStore,
) -> None:
    """An item with no library-location fields gets an empty {} for
    library_location, not None or a noisy dict of nulls."""
    result = await handle_get_item_details(
        {"item_key": "I2", "corpus": "zotero"},
        store=store_with_collections,
    )
    payload = json.loads(result[0].text)
    assert payload["item"]["library_location"] == {}


@pytest.mark.asyncio
async def test_get_item_details_includes_collections(
    store_with_collections: VectorStore,
) -> None:
    result = await handle_get_item_details(
        {"item_key": "I2", "corpus": "zotero"},
        store=store_with_collections,
    )
    payload = json.loads(result[0].text)
    cols = payload["item"]["collections"]
    assert len(cols) == 1
    assert cols[0]["name"] == "Caste Studies"
    assert cols[0]["collection_key"] == "C2"
    assert cols[0]["parent_key"] == "C1"
