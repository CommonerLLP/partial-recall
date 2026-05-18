"""Tests for ZoteroAdapter notes + annotations support (v0.2.0).

Builds a minimal Zotero-shaped SQLite from scratch — narrower than the
fixture snapshot — to exercise the note and annotation code paths.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.corpus.adapters.zotero import ZoteroAdapter, _strip_html

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

_BASE_SCHEMA = """
CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT NOT NULL);
INSERT INTO itemTypes VALUES (1, 'book'), (14, 'attachment'), (1024, 'note'),
    (1025, 'annotation'), (3, 'journalArticle');

CREATE TABLE items (
    itemID INTEGER PRIMARY KEY,
    itemTypeID INTEGER NOT NULL,
    key TEXT NOT NULL UNIQUE
);

CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);

CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT NOT NULL);
INSERT INTO fields VALUES (1, 'title'), (2, 'date'), (3, 'abstractNote');

CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE itemData (
    itemID INTEGER NOT NULL,
    fieldID INTEGER NOT NULL,
    valueID INTEGER NOT NULL,
    PRIMARY KEY (itemID, fieldID)
);

CREATE TABLE creators (
    creatorID INTEGER PRIMARY KEY,
    firstName TEXT,
    lastName TEXT
);
CREATE TABLE itemCreators (
    itemID INTEGER NOT NULL,
    creatorID INTEGER NOT NULL,
    orderIndex INTEGER NOT NULL,
    PRIMARY KEY (itemID, creatorID)
);

CREATE TABLE itemAttachments (
    itemID INTEGER PRIMARY KEY,
    parentItemID INTEGER,
    contentType TEXT,
    path TEXT
);

CREATE TABLE itemNotes (
    itemID INTEGER PRIMARY KEY,
    parentItemID INTEGER,
    note TEXT,
    title TEXT
);

CREATE TABLE itemAnnotations (
    itemID INTEGER PRIMARY KEY,
    parentItemID INTEGER NOT NULL,
    type INTEGER NOT NULL,
    text TEXT,
    comment TEXT,
    pageLabel TEXT,
    sortIndex TEXT NOT NULL,
    position TEXT NOT NULL,
    isExternal INTEGER NOT NULL DEFAULT 0
);
"""


def _build_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "zotero.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(_BASE_SCHEMA)
    # Parent item: BOOK1 (itemID=1, typeID=1=book)
    conn.execute("INSERT INTO items VALUES (1, 1, 'BOOK1')")
    conn.execute("INSERT INTO itemDataValues VALUES (1, 'A history of reading')")
    conn.execute("INSERT INTO itemData VALUES (1, 1, 1)")
    # PDF attachment for BOOK1 (itemID=2)
    conn.execute("INSERT INTO items VALUES (2, 14, 'PDFATT1')")
    conn.execute(
        "INSERT INTO itemAttachments VALUES (2, 1, 'application/pdf', 'storage:foo.pdf')"
    )
    # Standalone-ish: notes attached directly to parent (Zotero allows this)
    conn.execute("INSERT INTO items VALUES (3, 1024, 'NOTE0001')")
    conn.execute(
        "INSERT INTO itemNotes VALUES "
        "(3, 1, "
        "'<div class=\"zotero-note znv1\"><p>Reading was always <b>political</b>.</p>"
        "<p>See &amp; especially ch. 3.</p></div>', "
        "'Chapter overview')"
    )
    # Soft-deleted note: should be excluded
    conn.execute("INSERT INTO items VALUES (4, 1024, 'NOTEDEL1')")
    conn.execute(
        "INSERT INTO itemNotes VALUES "
        "(4, 1, '<p>this should not appear</p>', NULL)"
    )
    conn.execute("INSERT INTO deletedItems VALUES (4)")
    # Annotations on the PDF attachment (itemID=2 is the parent of these)
    # Highlight (type=1)
    conn.execute("INSERT INTO items VALUES (5, 1025, 'ANN0001')")
    conn.execute(
        "INSERT INTO itemAnnotations VALUES "
        "(5, 2, 1, 'pale-yellow wall', 'on land-bank gradient', '12', "
        "'00001|000001|00000', '{}', 0)"
    )
    # User-note annotation (type=2) without comment, no page label
    conn.execute("INSERT INTO items VALUES (6, 1025, 'ANN0002')")
    conn.execute(
        "INSERT INTO itemAnnotations VALUES "
        "(6, 2, 2, 'a planning idiom', NULL, NULL, "
        "'00002|000001|00000', '{}', 0)"
    )
    # Underline (type=5) — also textual
    conn.execute("INSERT INTO items VALUES (7, 1025, 'ANN0003')")
    conn.execute(
        "INSERT INTO itemAnnotations VALUES "
        "(7, 2, 5, 'underlined phrase', NULL, '14', "
        "'00003|000001|00000', '{}', 0)"
    )
    # Image annotation (type=3) — should be SKIPPED (no text)
    conn.execute("INSERT INTO items VALUES (8, 1025, 'ANNIMG1')")
    conn.execute(
        "INSERT INTO itemAnnotations VALUES "
        "(8, 2, 3, NULL, NULL, NULL, "
        "'00004|000001|00000', '{}', 0)"
    )
    # Ink annotation (type=4) — also skipped
    conn.execute("INSERT INTO items VALUES (9, 1025, 'ANNINK1')")
    conn.execute(
        "INSERT INTO itemAnnotations VALUES "
        "(9, 2, 4, NULL, NULL, NULL, "
        "'00005|000001|00000', '{}', 0)"
    )
    # Soft-deleted annotation: should be excluded
    conn.execute("INSERT INTO items VALUES (10, 1025, 'ANNDEL1')")
    conn.execute(
        "INSERT INTO itemAnnotations VALUES "
        "(10, 2, 1, 'should not appear', NULL, NULL, "
        "'00006|000001|00000', '{}', 0)"
    )
    conn.execute("INSERT INTO deletedItems VALUES (10)")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def adapter(tmp_path: Path) -> Iterator[ZoteroAdapter]:
    db = _build_db(tmp_path)
    storage = tmp_path / "storage"
    storage.mkdir()
    a = ZoteroAdapter(sqlite_path=db, storage_path=storage)
    yield a
    a.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_strip_html_handles_tags_entities_whitespace() -> None:
    src = (
        "<div class='x'><p>Reading was always <b>political</b>.</p>"
        "<p>See &amp;\n\nespecially ch.\t 3.</p></div>"
    )
    assert _strip_html(src) == "Reading was always political. See & especially ch. 3."
    assert _strip_html("") == ""
    assert _strip_html(None) == ""


def test_get_sources_yields_pdf_then_notes_then_annotations(adapter: ZoteroAdapter) -> None:
    item = next(i for i in adapter.list_items() if i.item_key == "BOOK1")
    sources = list(adapter.get_sources(item))
    source_types = [s.source_type for s in sources]
    # No abstract on this item (we only set a title), so no abstract source.
    assert source_types[0] == "pdf"
    # Notes follow PDFs
    assert "note" in source_types
    note_indices = [i for i, st in enumerate(source_types) if st == "note"]
    pdf_indices = [i for i, st in enumerate(source_types) if st == "pdf"]
    assert min(note_indices) > max(pdf_indices)
    # Annotations follow notes
    ann_indices = [i for i, st in enumerate(source_types) if st == "annotation"]
    assert min(ann_indices) > max(note_indices)


def test_only_textual_annotations_yielded(adapter: ZoteroAdapter) -> None:
    item = next(i for i in adapter.list_items() if i.item_key == "BOOK1")
    sources = list(adapter.get_sources(item))
    ann_refs = [s.source_ref for s in sources if s.source_type == "annotation"]
    # Three textual annotations expected (highlight, user-note, underline);
    # image/ink/deleted excluded.
    assert sorted(ann_refs) == ["annotation:ANN0001", "annotation:ANN0002", "annotation:ANN0003"]


def test_deleted_note_excluded(adapter: ZoteroAdapter) -> None:
    item = next(i for i in adapter.list_items() if i.item_key == "BOOK1")
    note_refs = [s.source_ref for s in adapter.get_sources(item) if s.source_type == "note"]
    assert note_refs == ["note:NOTE0001"]
    assert "note:NOTEDEL1" not in note_refs


def test_get_note_text_strips_html_and_prepends_title(adapter: ZoteroAdapter) -> None:
    item = next(i for i in adapter.list_items() if i.item_key == "BOOK1")
    src = next(s for s in adapter.get_sources(item) if s.source_type == "note")
    text = adapter.get_text(item, src)
    assert text is not None
    assert text.startswith("Chapter overview")
    assert "Reading was always political" in text
    # tags fully stripped
    assert "<" not in text
    assert ">" not in text


def test_get_annotation_text_combines_text_comment_page(adapter: ZoteroAdapter) -> None:
    item = next(i for i in adapter.list_items() if i.item_key == "BOOK1")
    srcs = {s.source_ref: s for s in adapter.get_sources(item) if s.source_type == "annotation"}

    # Highlight with comment + page label
    ann1 = adapter.get_text(item, srcs["annotation:ANN0001"])
    assert ann1 == "pale-yellow wall — on land-bank gradient (p. 12)"

    # User-note annotation: no comment, no page
    ann2 = adapter.get_text(item, srcs["annotation:ANN0002"])
    assert ann2 == "a planning idiom"

    # Underline with page only
    ann3 = adapter.get_text(item, srcs["annotation:ANN0003"])
    assert ann3 == "underlined phrase (p. 14)"


def test_get_sources_works_when_tables_missing(tmp_path: Path) -> None:
    """If the Zotero DB lacks itemNotes/itemAnnotations (trimmed fixture),
    the adapter should still produce abstracts + pdfs and just skip the
    missing source types — not raise."""
    db_path = tmp_path / "trimmed.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT NOT NULL);
        INSERT INTO itemTypes VALUES (1, 'book'), (14, 'attachment');
        CREATE TABLE items (
            itemID INTEGER PRIMARY KEY, itemTypeID INTEGER NOT NULL, key TEXT NOT NULL UNIQUE
        );
        CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT NOT NULL);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE itemData (
            itemID INTEGER NOT NULL, fieldID INTEGER NOT NULL, valueID INTEGER NOT NULL,
            PRIMARY KEY (itemID, fieldID)
        );
        CREATE TABLE creators (
            creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT
        );
        CREATE TABLE itemCreators (
            itemID INTEGER NOT NULL, creatorID INTEGER NOT NULL, orderIndex INTEGER NOT NULL,
            PRIMARY KEY (itemID, creatorID)
        );
        CREATE TABLE itemAttachments (
            itemID INTEGER PRIMARY KEY, parentItemID INTEGER,
            contentType TEXT, path TEXT
        );
        INSERT INTO items VALUES (1, 1, 'B1');
        """
    )
    conn.commit()
    conn.close()
    storage = tmp_path / "storage"
    storage.mkdir()
    a = ZoteroAdapter(sqlite_path=db_path, storage_path=storage)
    try:
        assert a._has_notes is False
        assert a._has_annotations is False
        items = list(a.list_items())
        assert [i.item_key for i in items] == ["B1"]
        sources = list(a.get_sources(items[0]))
        assert all(s.source_type != "note" for s in sources)
        assert all(s.source_type != "annotation" for s in sources)
    finally:
        a.close()
