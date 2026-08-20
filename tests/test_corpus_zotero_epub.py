"""EPUB-only and DOCX-only Zotero attachments must index and fetch.

Before this, `get_sources` yielded an `epub:<key>` source but the path
resolver only accepted a `pdf:` prefix and a `.pdf` suffix. `get_text`
therefore returned None, the item produced 0 chunks, and `fetch_item`
reported no attachment. Both are real false negatives seen in use.
"""

from __future__ import annotations

import shutil
import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.config.models import ZoteroConfig
from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.corpus.zotero_fetch import fetch_zotero_attachment

EPUB_BODY = "Ambedkar on the separation of the polity from the society."
DOCX_BODY = "A working note on library provisioning."


def _write_epub(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("OEBPS/ch1.xhtml", f"<html><body><p>{body}</p></body></html>")


def _write_docx(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
        f"{body}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


@pytest.fixture
def library(fixtures_dir: Path, tmp_path: Path) -> tuple[Path, Path]:
    """A copy of the snapshot with two attachment-only parents added.

    EPUBITEM has one EPUB and nothing else. DOCXITEM has one DOCX and
    nothing else. The checked-in snapshot is never modified.
    """
    db = tmp_path / "zotero.sqlite"
    storage = tmp_path / "storage"
    shutil.copy(fixtures_dir / "zotero_snapshot" / "zotero.sqlite", db)
    shutil.copytree(fixtures_dir / "zotero_snapshot" / "storage", storage)

    con = sqlite3.connect(db)
    con.executemany(
        "INSERT INTO items (itemID, itemTypeID, key, dateAdded, dateModified, libraryID)"
        " VALUES (?, ?, ?, ?, ?, 1)",
        [
            (10, 4, "EPUBITEM", "2024-01-01", "2024-01-01"),
            (11, 2, "EPUBATT1", "2024-01-01", "2024-01-01"),
            (12, 4, "DOCXITEM", "2024-01-01", "2024-01-01"),
            (13, 2, "DOCXATT1", "2024-01-01", "2024-01-01"),
        ],
    )
    con.executemany(
        "INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, path)"
        " VALUES (?, ?, 1, ?, ?)",
        [
            (11, 10, "application/epub+zip", "storage:book.epub"),
            (13, 12, "application/vnd.openxmlformats-officedocument."
                     "wordprocessingml.document", "storage:note.docx"),
        ],
    )
    con.commit()
    con.close()

    _write_epub(storage / "EPUBATT1" / "book.epub", EPUB_BODY)
    _write_docx(storage / "DOCXATT1" / "note.docx", DOCX_BODY)
    return db, storage


@pytest.fixture
def adapter(library: tuple[Path, Path]) -> Iterator[ZoteroAdapter]:
    a = ZoteroAdapter(sqlite_path=library[0], storage_path=library[1])
    yield a
    a.close()


def _source(adapter: ZoteroAdapter, item_key: str, source_type: str):
    item = {i.item_key: i for i in adapter.list_items()}[item_key]
    for source in adapter.get_sources(item):
        if source.source_type == source_type:
            return item, source
    raise AssertionError(f"no {source_type} source on {item_key}")


def test_epub_source_ref_uses_the_epub_prefix(adapter: ZoteroAdapter) -> None:
    _, source = _source(adapter, "EPUBITEM", "epub")
    assert source.source_ref == "epub:EPUBATT1"


def test_epub_only_item_yields_text(adapter: ZoteroAdapter) -> None:
    item, source = _source(adapter, "EPUBITEM", "epub")
    text = adapter.get_text(item, source)
    assert text is not None
    assert EPUB_BODY in text


def test_docx_only_item_yields_text(adapter: ZoteroAdapter) -> None:
    item, source = _source(adapter, "DOCXITEM", "docx")
    text = adapter.get_text(item, source)
    assert text is not None
    assert DOCX_BODY in text


def test_source_type_comes_from_content_type_not_the_path(
    library: tuple[Path, Path],
) -> None:
    """An attachment with a NULL path still resolves by contentType."""
    db, storage = library
    con = sqlite3.connect(db)
    con.execute("UPDATE itemAttachments SET path = NULL WHERE itemID = 11")
    con.commit()
    con.close()
    a = ZoteroAdapter(sqlite_path=db, storage_path=storage)
    try:
        _, source = _source(a, "EPUBITEM", "epub")
        assert source.source_ref == "epub:EPUBATT1"
    finally:
        a.close()


def test_pdf_ref_never_resolves_to_an_epub(adapter: ZoteroAdapter) -> None:
    """Prefix and suffix must agree, or a mixed item returns the wrong file."""
    item, source = _source(adapter, "EPUBITEM", "epub")
    mislabelled = type(source)(
        source_type="pdf", source_ref="pdf:EPUBATT1", kind=source.kind
    )
    assert adapter.get_text(item, mislabelled) is None


def test_fetch_finds_an_epub_only_attachment(
    library: tuple[Path, Path], tmp_path: Path
) -> None:
    db, storage = library
    a = ZoteroAdapter(sqlite_path=db, storage_path=storage)
    try:
        res = fetch_zotero_attachment(
            item_key="EPUBITEM",
            adapter=a,
            config=ZoteroConfig(sqlite_path=db, storage_path=storage),
            cache_dir=tmp_path / "cache",
            download_missing=False,
            extract_text=True,
        )
    finally:
        a.close()
    assert res.attachment_key == "EPUBATT1"
    assert res.path is not None
    assert res.path.suffix == ".epub"
    assert res.source == "local"
    assert res.text is not None
    assert EPUB_BODY in res.text


def test_fetch_prefers_the_pdf_when_an_item_has_both(
    library: tuple[Path, Path], tmp_path: Path
) -> None:
    db, storage = library
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO items (itemID, itemTypeID, key, dateAdded, dateModified, libraryID)"
        " VALUES (14, 2, 'EPUBATT2', '2024-01-01', '2024-01-01', 1)"
    )
    con.execute(
        "INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, path)"
        " VALUES (14, 10, 1, 'application/pdf', 'storage:book.pdf')"
    )
    con.commit()
    con.close()
    shutil.copy(
        storage / "PDFITEM01" / "paper.pdf",
        _mkdir(storage / "EPUBATT2") / "book.pdf",
    )
    a = ZoteroAdapter(sqlite_path=db, storage_path=storage)
    try:
        res = fetch_zotero_attachment(
            item_key="EPUBITEM",
            adapter=a,
            config=ZoteroConfig(sqlite_path=db, storage_path=storage),
            cache_dir=tmp_path / "cache",
            download_missing=False,
            extract_text=False,
        )
    finally:
        a.close()
    assert res.attachment_key == "EPUBATT2"
    assert res.path is not None
    assert res.path.suffix == ".pdf"


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
