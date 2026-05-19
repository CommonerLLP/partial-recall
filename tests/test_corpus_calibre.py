"""Tests for CalibreAdapter (v0.3.0).

We build a minimal metadata.db that mirrors Calibre's actual schema
(just the tables we use) so no Calibre installation is needed.
"""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from partial_recall.corpus.adapters.calibre import CalibreAdapter
from partial_recall.errors import CorpusUnavailableError

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_calibre_db(tmp_path: Path) -> Path:
    """Create a minimal Calibre metadata.db with a handful of books."""
    db_path = tmp_path / "metadata.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE books (
            id      INTEGER PRIMARY KEY,
            title   TEXT NOT NULL DEFAULT 'Unknown',
            pubdate TEXT,
            timestamp TEXT,
            path    TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE authors (
            id   INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE books_authors_link (
            book   INTEGER REFERENCES books(id),
            author INTEGER REFERENCES authors(id)
        );
        CREATE TABLE comments (
            id   INTEGER PRIMARY KEY,
            book INTEGER REFERENCES books(id),
            text TEXT NOT NULL
        );
        CREATE TABLE data (
            id     INTEGER PRIMARY KEY,
            book   INTEGER REFERENCES books(id),
            format TEXT NOT NULL,
            name   TEXT NOT NULL
        );

        INSERT INTO books VALUES
            (1,'Annihilation of Caste','1936-01-01','2024-01-01','Ambedkar_B_R/Annihilation');
        INSERT INTO books VALUES
            (2,'Prison Notebooks','1971-01-01','2024-01-01','Gramsci_Antonio/Prison_Notebooks');

        INSERT INTO authors VALUES (1, 'Ambedkar, B. R.');
        INSERT INTO authors VALUES (2, 'Gramsci, Antonio');

        INSERT INTO books_authors_link VALUES (1, 1);
        INSERT INTO books_authors_link VALUES (2, 2);

        INSERT INTO comments VALUES (1, 1, 'A speech prepared but not delivered.');

        INSERT INTO data VALUES (1, 1, 'PDF', 'Annihilation');
        INSERT INTO data VALUES (2, 2, 'EPUB', 'Prison_Notebooks');
    """)
    conn.commit()
    conn.close()
    return tmp_path


def _make_library(tmp_path: Path) -> Path:
    """Create a Calibre library folder with metadata.db and placeholder files."""
    _make_calibre_db(tmp_path)
    # Create book folders + placeholder files so file-resolution tests pass
    book1_dir = tmp_path / "Ambedkar_B_R" / "Annihilation"
    book1_dir.mkdir(parents=True)
    (book1_dir / "Annihilation.pdf").write_bytes(b"%PDF-1.4")
    book2_dir = tmp_path / "Gramsci_Antonio" / "Prison_Notebooks"
    book2_dir.mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_rejects_missing_library(tmp_path: Path) -> None:
    with pytest.raises(CorpusUnavailableError, match="not found"):
        CalibreAdapter(library_path=tmp_path / "nonexistent")


def test_rejects_missing_metadata_db(tmp_path: Path) -> None:
    with pytest.raises(CorpusUnavailableError, match="metadata.db not found"):
        CalibreAdapter(library_path=tmp_path)


def test_accepts_valid_library(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    assert adapter.name == "calibre"
    adapter.close()


# ---------------------------------------------------------------------------
# list_items
# ---------------------------------------------------------------------------


def test_list_items_count(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    items = list(adapter.list_items())
    assert len(items) == 2
    adapter.close()


def test_list_items_corpus_is_calibre(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    items = list(adapter.list_items())
    assert all(i.corpus == "calibre" for i in items)
    adapter.close()


def test_list_items_titles(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    titles = {i.title for i in adapter.list_items()}
    assert "Annihilation of Caste" in titles
    assert "Prison Notebooks" in titles
    adapter.close()


def test_list_items_abstract_populated(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    items = {i.title: i for i in adapter.list_items()}
    assert items["Annihilation of Caste"].abstract == "A speech prepared but not delivered."
    assert items["Prison Notebooks"].abstract is None
    adapter.close()


def test_list_items_author_parsed(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    items = {i.title: i for i in adapter.list_items()}
    creators = items["Annihilation of Caste"].creators
    assert len(creators) == 1
    assert creators[0]["last"] == "Ambedkar"
    adapter.close()


def test_item_key_stable(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    items1 = list(adapter.list_items())
    items2 = list(adapter.list_items())
    assert items1[0].item_key == items2[0].item_key
    adapter.close()


def test_count_items(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    assert adapter.count_items() == 2
    adapter.close()


# ---------------------------------------------------------------------------
# get_sources
# ---------------------------------------------------------------------------


def test_get_sources_abstract_when_present(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    items = {i.title: i for i in adapter.list_items()}
    sources = list(adapter.get_sources(items["Annihilation of Caste"]))
    types = {s.source_type for s in sources}
    assert "abstract" in types
    adapter.close()


def test_get_sources_pdf_when_file_exists(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    items = {i.title: i for i in adapter.list_items()}
    sources = list(adapter.get_sources(items["Annihilation of Caste"]))
    types = {s.source_type for s in sources}
    assert "pdf" in types
    adapter.close()


def test_get_sources_no_abstract_no_file(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    items = {i.title: i for i in adapter.list_items()}
    # Prison Notebooks has no abstract and its EPUB file doesn't exist
    sources = list(adapter.get_sources(items["Prison Notebooks"]))
    assert sources == []
    adapter.close()


# ---------------------------------------------------------------------------
# get_text
# ---------------------------------------------------------------------------


def test_get_text_abstract(tmp_path: Path) -> None:
    _make_library(tmp_path)
    adapter = CalibreAdapter(library_path=tmp_path)
    items = {i.title: i for i in adapter.list_items()}
    item = items["Annihilation of Caste"]
    sources = list(adapter.get_sources(item))
    abstract_src = next(s for s in sources if s.source_type == "abstract")
    assert adapter.get_text(item, abstract_src) == "A speech prepared but not delivered."
    adapter.close()


# ---------------------------------------------------------------------------
# EPUB extraction
# ---------------------------------------------------------------------------


def _make_epub(path: Path, text: str) -> None:
    """Write a minimal valid EPUB with one HTML content file."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "content.html",
            f"<html><body><p>{text}</p></body></html>",
        )


def test_epub_extraction(tmp_path: Path) -> None:
    from partial_recall.extract.epub import extract_epub_text
    epub = tmp_path / "test.epub"
    _make_epub(epub, "Hegemony is the leadership of a social group.")
    assert extract_epub_text(epub) is not None
    assert "Hegemony" in extract_epub_text(epub)


def test_epub_extraction_bad_zip(tmp_path: Path) -> None:
    from partial_recall.extract.epub import extract_epub_text
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"not a zip")
    assert extract_epub_text(bad) is None
