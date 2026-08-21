"""Multi-volume sets must be distinguishable in results (#41).

The adapter read `volume`, `edition`, `series`, and friends from SQLite
and dropped them. Every volume of a collected-works edition shares one
title, one date, and one set of creators, so search returned N identical
results and a caller had to open the PDFs to learn which volume a hit
came from.

Filenames are not a workaround. In the set that surfaced this, the file
named "...speeches 18.pdf" is Volume 17 Part One.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.corpus.adapters.zotero import ZoteroAdapter

BIB_FIELDS = (
    "volume", "edition", "series", "seriesNumber",
    "numberOfVolumes", "publisher", "place",
)


@pytest.fixture
def library(fixtures_dir: Path, tmp_path: Path) -> Path:
    """A snapshot copy holding a three-volume set of one work.

    All three share title, date, and creators. Only `volume` differs.
    """
    db = tmp_path / "zotero.sqlite"
    shutil.copy(fixtures_dir / "zotero_snapshot" / "zotero.sqlite", db)
    con = sqlite3.connect(db)

    next_value = con.execute("SELECT MAX(valueID) FROM itemDataValues").fetchone()[0] + 1

    def field_id(name: str) -> int:
        """Resolve a field id, adding the field only when it is absent.

        The snapshot already defines title and abstractNote. Re-adding
        them would collide, and falling back to another field's id would
        silently write the value into the wrong column.
        """
        row = con.execute(
            "SELECT fieldID FROM fields WHERE fieldName = ?", (name,)
        ).fetchone()
        if row is not None:
            return int(row[0])
        nid = con.execute("SELECT MAX(fieldID) FROM fields").fetchone()[0] + 1
        con.execute(
            "INSERT INTO fields (fieldID, fieldName) VALUES (?, ?)", (nid, name)
        )
        return int(nid)

    for name in BIB_FIELDS:
        field_id(name)

    def put(item_id: int, field: str, value: str) -> None:
        nonlocal next_value
        con.execute(
            "INSERT INTO itemDataValues (valueID, value) VALUES (?, ?)",
            (next_value, value),
        )
        con.execute(
            "INSERT INTO itemData (itemID, fieldID, valueID) VALUES (?, ?, ?)",
            (item_id, field_id(field), next_value),
        )
        next_value += 1

    for n, (item_id, key) in enumerate(
        [(20, "VOLONE00"), (21, "VOLTWO00"), (22, "VOLTHR00")], start=1
    ):
        con.execute(
            "INSERT INTO items (itemID, itemTypeID, key, dateAdded, dateModified, libraryID)"
            " VALUES (?, 4, ?, '2024-01-01', '2024-01-01', 1)",
            (item_id, key),
        )
        con.execute(
            "INSERT INTO itemDataValues (valueID, value) VALUES (?, ?)",
            (next_value, "Writings and Speeches"),
        )
        con.execute(
            "INSERT INTO itemData (itemID, fieldID, valueID) VALUES (?, ?, ?)",
            (item_id, field_id("title"), next_value),
        )
        next_value += 1
        put(item_id, "volume", str(n))
        put(item_id, "series", "Collected Works")
        put(item_id, "numberOfVolumes", "3")
        # Give each volume text, or nothing reaches the chunk table and
        # the search assertions have nothing to find. The text is IDENTICAL
        # across the three, which is the real shape of a collected-works
        # set and what makes the metadata-hash assertion meaningful.
        put(item_id, "abstractNote", "Writings and Speeches, collected edition.")
    con.commit()
    con.close()
    return db


@pytest.fixture
def adapter(library: Path, tmp_path: Path) -> Iterator[ZoteroAdapter]:
    a = ZoteroAdapter(sqlite_path=library, storage_path=tmp_path / "storage")
    yield a
    a.close()


def _volumes(adapter: ZoteroAdapter) -> dict[str, object]:
    return {
        i.item_key: i
        for i in adapter.list_items()
        if i.item_key in {"VOLONE00", "VOLTWO00", "VOLTHR00"}
    }


def test_volume_is_carried_onto_the_item(adapter: ZoteroAdapter) -> None:
    items = _volumes(adapter)
    assert len(items) == 3
    assert {i.volume for i in items.values()} == {"1", "2", "3"}


def test_series_and_count_are_carried(adapter: ZoteroAdapter) -> None:
    item = _volumes(adapter)["VOLONE00"]
    assert item.series == "Collected Works"
    assert item.number_of_volumes == "3"


def test_the_three_volumes_are_otherwise_identical(adapter: ZoteroAdapter) -> None:
    """The premise of the bug. Without volume there is nothing to tell them apart."""
    items = list(_volumes(adapter).values())
    assert len({i.title for i in items}) == 1
    assert len({i.date for i in items}) == 1


def test_metadata_hashes_no_longer_collide(adapter: ZoteroAdapter) -> None:
    """Three volumes hashed identically before, because the hash saw only
    the fields the whole set shares."""
    items = list(_volumes(adapter).values())
    assert len({i.metadata_hash for i in items}) == 3


def test_an_item_without_these_fields_keeps_them_none(adapter: ZoteroAdapter) -> None:
    """A single-volume item must not gain empty strings."""
    plain = {i.item_key: i for i in adapter.list_items()}["ITEM01XX"]
    assert plain.volume is None
    assert plain.series is None
    assert plain.publisher is None


# ---------------------------------------------------------------------------
# End to end: the fields must reach the MCP output, not just the Item.
# ---------------------------------------------------------------------------


@pytest.fixture
def indexed(library: Path, tmp_path: Path):
    from partial_recall.index.pipeline import run_indexing
    from partial_recall.store.vector_store import VectorStore
    from tests.test_pipeline import FakeEmbeddingProvider

    adapter = ZoteroAdapter(sqlite_path=library, storage_path=tmp_path / "storage")
    store = VectorStore(tmp_path / "vectors.sqlite")
    run_indexing(adapter=adapter, store=store, provider=FakeEmbeddingProvider())
    yield store
    adapter.close()
    store.close()


@pytest.mark.asyncio
async def test_get_item_details_returns_the_volume(indexed) -> None:
    import json

    from partial_recall.mcp.tools.get_item_details import handle_get_item_details

    payload = json.loads(
        (await handle_get_item_details(
            {"item_key": "VOLTWO00", "corpus": "zotero"}, store=indexed,
        ))[0].text
    )
    bib = payload["item"]["bibliographic"]
    assert bib["volume"] == "2"
    assert bib["series"] == "Collected Works"
    assert bib["number_of_volumes"] == "3"


@pytest.mark.asyncio
async def test_empty_fields_are_dropped_from_the_payload(indexed) -> None:
    """A populated-only payload keeps single-volume items compact."""
    import json

    from partial_recall.mcp.tools.get_item_details import handle_get_item_details

    payload = json.loads(
        (await handle_get_item_details(
            {"item_key": "VOLTWO00", "corpus": "zotero"}, store=indexed,
        ))[0].text
    )
    bib = payload["item"]["bibliographic"]
    assert "edition" not in bib
    assert "publisher" not in bib


@pytest.mark.asyncio
async def test_fulltext_search_results_carry_the_volume(indexed) -> None:
    """The issue's core complaint: a hit must be citable to a volume."""
    import json

    from partial_recall.mcp.tools.search_fulltext import handle_search_fulltext

    payload = json.loads(
        (await handle_search_fulltext(
            {"query": "Writings", "top_k": 10}, store=indexed,
        ))[0].text
    )
    volumes = {r.get("volume") for r in payload["results"] if r.get("title")}
    assert volumes >= {"1", "2", "3"}, payload["results"]
