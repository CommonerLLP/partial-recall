"""Tests for the library_search MCP tool.

Builds a minimal in-memory Zotero-schema SQLite fixture — the same
tables that ZoteroAdapter and _run_library_search depend on — so tests
run offline with no real Zotero installation required.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from partial_recall.mcp.tools.library_search import handle_library_search

# ---------------------------------------------------------------------------
# Zotero SQLite fixture
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
CREATE TABLE items (
    itemID INTEGER PRIMARY KEY,
    key TEXT UNIQUE,
    itemTypeID INTEGER,
    dateAdded TEXT
);
CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
CREATE TABLE deletedCollections (collectionID INTEGER PRIMARY KEY);
CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
CREATE TABLE creators (
    creatorID INTEGER PRIMARY KEY,
    firstName TEXT,
    lastName TEXT
);
CREATE TABLE itemCreators (
    itemID INTEGER,
    creatorID INTEGER,
    orderIndex INTEGER
);
CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER);
CREATE TABLE collections (
    collectionID INTEGER PRIMARY KEY,
    key TEXT,
    collectionName TEXT,
    parentCollectionID INTEGER
);
CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
"""


def _build_fixture(path: Path) -> None:
    """Populate a minimal Zotero-schema DB with four test items."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)

    # Item types
    conn.executemany(
        "INSERT INTO itemTypes VALUES (?,?)",
        [(1, "journalArticle"), (2, "book"), (3, "attachment"), (4, "note")],
    )

    # Fields
    conn.executemany(
        "INSERT INTO fields VALUES (?,?)",
        [
            (1, "title"),
            (2, "date"),
            (3, "abstractNote"),
            (4, "publicationTitle"),
        ],
    )

    # Items: (itemID, key, typeID, dateAdded)
    conn.executemany(
        "INSERT INTO items VALUES (?,?,?,?)",
        [
            (1, "AAAA0001", 1, "2024-01-10 10:00:00"),  # journalArticle
            (2, "BBBB0002", 2, "2023-06-15 08:00:00"),  # book
            (3, "CCCC0003", 1, "2025-03-01 12:00:00"),  # journalArticle
            (4, "DDDD0004", 2, "2022-11-20 09:00:00"),  # book
        ],
    )

    # itemDataValues
    conn.executemany(
        "INSERT INTO itemDataValues VALUES (?,?)",
        [
            (1, "Caste and Capital"),
            (2, "2010"),
            (3, "Abstract about caste and economy"),
            (4, "Economic and Political Weekly"),
            (5, "Ambedkar and the Nation"),
            (6, "1945"),
            (7, "A study of Ambedkar's constitutional vision"),
            (8, "Oxford University Press"),
            (9, "Labour and Dignity"),
            (10, "2020"),
            (11, "Abstract about labour rights"),
            (12, "Modern Asian Studies"),
            (13, "Village Society"),
            (14, "1990"),
            (15, "Abstract on rural India"),
            (16, "Cambridge University Press"),
        ],
    )

    # itemData: (itemID, fieldID, valueID)
    conn.executemany(
        "INSERT INTO itemData VALUES (?,?,?)",
        [
            (1, 1, 1), (1, 2, 2), (1, 3, 3), (1, 4, 4),   # item 1
            (2, 1, 5), (2, 2, 6), (2, 3, 7), (2, 4, 8),   # item 2
            (3, 1, 9), (3, 2, 10), (3, 3, 11), (3, 4, 12),  # item 3
            (4, 1, 13), (4, 2, 14), (4, 3, 15), (4, 4, 16),  # item 4
        ],
    )

    # Creators
    conn.executemany(
        "INSERT INTO creators VALUES (?,?,?)",
        [
            (1, "Ananya", "Gopal"),
            (2, "Ravi", "Hirway"),
            (3, "B.R.", "Ambedkar"),
            (4, "Susan", "Hirway"),
        ],
    )

    # itemCreators: item1→Gopal, item2→Ambedkar, item3→Hirway(Ravi), item4→Hirway(Susan)
    conn.executemany(
        "INSERT INTO itemCreators VALUES (?,?,?)",
        [(1, 1, 0), (2, 3, 0), (3, 2, 0), (4, 4, 0)],
    )

    # Tags
    conn.executemany(
        "INSERT INTO tags VALUES (?,?)",
        [(1, "caste"), (2, "economy"), (3, "ambedkar"), (4, "labour")],
    )

    # itemTags: item1→caste,economy; item2→caste,ambedkar; item3→labour; item4→caste
    conn.executemany(
        "INSERT INTO itemTags VALUES (?,?)",
        [(1, 1), (1, 2), (2, 1), (2, 3), (3, 4), (4, 1)],
    )

    # Collections
    conn.executemany(
        "INSERT INTO collections VALUES (?,?,?,?)",
        [(1, "COLL0001", "theory", None), (2, "COLL0002", "history", None)],
    )

    # collectionItems: theory→item1,item2; history→item3,item4
    conn.executemany(
        "INSERT INTO collectionItems VALUES (?,?)",
        [(1, 1), (1, 2), (2, 3), (2, 4)],
    )

    conn.commit()
    conn.close()


@pytest.fixture
def zotero_db(tmp_path: Path) -> Path:
    db = tmp_path / "zotero.sqlite"
    _build_fixture(db)
    return db


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _call(args: dict, db: Path) -> dict:
    results = await handle_library_search(args, zotero_sqlite_path=db)
    return json.loads(results[0].text)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_filters_returns_all_items(zotero_db: Path) -> None:
    out = await _call({}, zotero_db)
    assert out["total"] == 4
    keys = {r["item_key"] for r in out["results"]}
    assert keys == {"AAAA0001", "BBBB0002", "CCCC0003", "DDDD0004"}


@pytest.mark.asyncio
async def test_creator_filter_last_name(zotero_db: Path) -> None:
    out = await _call({"creators": ["Hirway"]}, zotero_db)
    assert out["total"] == 2
    keys = {r["item_key"] for r in out["results"]}
    assert keys == {"CCCC0003", "DDDD0004"}


@pytest.mark.asyncio
async def test_creator_filter_case_insensitive(zotero_db: Path) -> None:
    out = await _call({"creators": ["hirway"]}, zotero_db)
    assert out["total"] == 2


@pytest.mark.asyncio
async def test_tag_filter_single(zotero_db: Path) -> None:
    out = await _call({"tags": ["caste"]}, zotero_db)
    assert out["total"] == 3
    keys = {r["item_key"] for r in out["results"]}
    assert "CCCC0003" not in keys  # item3 has labour, not caste


@pytest.mark.asyncio
async def test_tag_filter_all_required(zotero_db: Path) -> None:
    # Only item1 has BOTH caste AND economy
    out = await _call({"tags": ["caste", "economy"]}, zotero_db)
    assert out["total"] == 1
    assert out["results"][0]["item_key"] == "AAAA0001"


@pytest.mark.asyncio
async def test_collection_filter(zotero_db: Path) -> None:
    out = await _call({"collections": ["theory"]}, zotero_db)
    assert out["total"] == 2
    keys = {r["item_key"] for r in out["results"]}
    assert keys == {"AAAA0001", "BBBB0002"}


@pytest.mark.asyncio
async def test_item_type_filter(zotero_db: Path) -> None:
    out = await _call({"item_types": ["book"]}, zotero_db)
    assert out["total"] == 2
    assert all(r["item_type"] == "book" for r in out["results"])


@pytest.mark.asyncio
async def test_year_min_filter(zotero_db: Path) -> None:
    # item3 pub year=2020 qualifies; item1 pub year=2010 does not
    out = await _call({"year_min": 2015}, zotero_db)
    assert out["total"] == 1
    assert out["results"][0]["year"] == 2020


@pytest.mark.asyncio
async def test_year_max_filter(zotero_db: Path) -> None:
    out = await _call({"year_max": 2000}, zotero_db)
    assert out["total"] == 2
    years = {r["year"] for r in out["results"]}
    assert all(y <= 2000 for y in years)


@pytest.mark.asyncio
async def test_year_range_combined(zotero_db: Path) -> None:
    out = await _call({"year_min": 2005, "year_max": 2015}, zotero_db)
    assert out["total"] == 1
    assert out["results"][0]["item_key"] == "AAAA0001"


@pytest.mark.asyncio
async def test_query_freetext_title(zotero_db: Path) -> None:
    out = await _call({"query": "Ambedkar"}, zotero_db)
    assert out["total"] == 1
    assert out["results"][0]["item_key"] == "BBBB0002"


@pytest.mark.asyncio
async def test_query_freetext_abstract(zotero_db: Path) -> None:
    out = await _call({"query": "labour"}, zotero_db)
    # matches item3 title AND item3 abstract
    keys = {r["item_key"] for r in out["results"]}
    assert "CCCC0003" in keys


@pytest.mark.asyncio
async def test_sort_year_asc(zotero_db: Path) -> None:
    out = await _call({"sort_by": "year_asc"}, zotero_db)
    years = [r["year"] for r in out["results"]]
    assert years == sorted(years)


@pytest.mark.asyncio
async def test_sort_year_desc(zotero_db: Path) -> None:
    out = await _call({"sort_by": "year_desc"}, zotero_db)
    years = [r["year"] for r in out["results"]]
    assert years == sorted(years, reverse=True)


@pytest.mark.asyncio
async def test_added_after_filter(zotero_db: Path) -> None:
    out = await _call({"added_after": "2024-01-01"}, zotero_db)
    assert out["total"] == 2
    keys = {r["item_key"] for r in out["results"]}
    assert keys == {"AAAA0001", "CCCC0003"}


@pytest.mark.asyncio
async def test_limit_respected(zotero_db: Path) -> None:
    out = await _call({"limit": 2}, zotero_db)
    assert len(out["results"]) == 2


@pytest.mark.asyncio
async def test_result_shape(zotero_db: Path) -> None:
    out = await _call({"creators": ["Gopal"]}, zotero_db)
    assert out["total"] == 1
    r = out["results"][0]
    assert r["item_key"] == "AAAA0001"
    assert r["item_type"] == "journalArticle"
    assert r["title"] == "Caste and Capital"
    assert r["year"] == 2010
    assert {"first": "Ananya", "last": "Gopal"} in r["creators"]
    assert "caste" in r["tags"]
    assert "theory" in r["collections"]


@pytest.mark.asyncio
async def test_no_zotero_path_returns_error() -> None:
    out = await handle_library_search({}, zotero_sqlite_path=None)
    payload = json.loads(out[0].text)
    assert "error" in payload


@pytest.mark.asyncio
async def test_missing_db_returns_error(tmp_path: Path) -> None:
    out = await handle_library_search({}, zotero_sqlite_path=tmp_path / "nope.sqlite")
    payload = json.loads(out[0].text)
    assert "error" in payload


@pytest.mark.asyncio
async def test_combined_filters(zotero_db: Path) -> None:
    # caste tag + book type → item2 and item4; then year_max=1950 → only item2
    out = await _call(
        {"tags": ["caste"], "item_types": ["book"], "year_max": 1950},
        zotero_db,
    )
    assert out["total"] == 1
    assert out["results"][0]["item_key"] == "BBBB0002"
