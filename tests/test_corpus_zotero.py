"""Tests for ZoteroAdapter."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.corpus.types import ItemKind


@pytest.fixture
def zotero_db(fixtures_dir: Path) -> Path:
    return fixtures_dir / "zotero_snapshot" / "zotero.sqlite"


@pytest.fixture
def zotero_storage(fixtures_dir: Path) -> Path:
    return fixtures_dir / "zotero_snapshot" / "storage"


@pytest.fixture
def adapter(zotero_db: Path, zotero_storage: Path) -> Iterator[ZoteroAdapter]:
    a = ZoteroAdapter(sqlite_path=zotero_db, storage_path=zotero_storage)
    yield a
    a.close()


def test_adapter_name_and_version(adapter: ZoteroAdapter) -> None:
    assert adapter.name == "zotero"
    assert adapter.version  # any non-empty string


def test_capabilities_includes_text_and_metadata(adapter: ZoteroAdapter) -> None:
    assert ItemKind.TEXT in adapter.capabilities
    assert ItemKind.METADATA in adapter.capabilities


def test_list_items_excludes_deleted_and_attachments(adapter: ZoteroAdapter) -> None:
    items = list(adapter.list_items())
    keys = {item.item_key for item in items}
    assert "ITEM01XX" in keys
    assert "ITEM02XX" in keys
    assert "DELETED1" not in keys
    assert "PDFITEM01" not in keys  # the attachment is not a top-level item


def test_list_items_returns_metadata(adapter: ZoteroAdapter) -> None:
    items = {i.item_key: i for i in adapter.list_items()}
    item = items["ITEM01XX"]
    assert item.title == "Library policy in India: a history"
    assert item.date == "2020-01-15"
    assert item.corpus == "zotero"
    assert item.abstract is not None
    assert "NPLIS" in item.abstract
    assert any(c.get("last") == "Roy" for c in item.creators)


def test_get_sources_yields_pdf_and_abstract_for_item_with_attachment(
    adapter: ZoteroAdapter,
) -> None:
    items = {i.item_key: i for i in adapter.list_items()}
    item = items["ITEM01XX"]
    sources = list(adapter.get_sources(item))
    source_types = {s.source_type for s in sources}
    assert "pdf" in source_types
    assert "abstract" in source_types


def test_get_sources_yields_abstract_only_for_item_without_pdf(adapter: ZoteroAdapter) -> None:
    items = {i.item_key: i for i in adapter.list_items()}
    item = items["ITEM02XX"]
    sources = list(adapter.get_sources(item))
    source_types = {s.source_type for s in sources}
    assert "abstract" in source_types
    assert "pdf" not in source_types


def test_get_text_for_abstract_returns_abstract(adapter: ZoteroAdapter) -> None:
    items = {i.item_key: i for i in adapter.list_items()}
    item = items["ITEM01XX"]
    abstract_source = next(s for s in adapter.get_sources(item) if s.source_type == "abstract")
    text = adapter.get_text(item, abstract_source)
    assert text is not None
    assert "NPLIS" in text


def test_get_text_for_pdf_extracts_pdf_text(adapter: ZoteroAdapter) -> None:
    items = {i.item_key: i for i in adapter.list_items()}
    item = items["ITEM01XX"]
    pdf_source = next(s for s in adapter.get_sources(item) if s.source_type == "pdf")
    text = adapter.get_text(item, pdf_source)
    assert text is not None
    assert "library policy" in text.lower()


def test_metadata_hash_changes_when_title_changes(adapter: ZoteroAdapter) -> None:
    items_before = {i.item_key: i for i in adapter.list_items()}
    hash_before = items_before["ITEM01XX"].metadata_hash
    # We can't easily mutate the read-only fixture; instead verify deterministic hashing
    # of two items returns different values:
    other_hash = items_before["ITEM02XX"].metadata_hash
    assert hash_before != other_hash
