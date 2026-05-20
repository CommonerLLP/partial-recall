"""Tests for JabRefAdapter (v0.3.0).

bibtexparser is an optional dep. Tests that exercise the parser run only
if it is installed (marked slow=False since install is cheap). The
structural tests mock the loaded library so they run in CI without the dep.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from partial_recall.corpus.adapters.jabref import (
    JabRefAdapter,
    JabRefAdapterError,
    _parse_authors,
    _resolve_file_links,
)
from partial_recall.errors import CorpusUnavailableError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_BIB = """\
@article{ambedkar1936,
  title     = {Annihilation of Caste},
  author    = {Ambedkar, B. R.},
  year      = {1936},
  abstract  = {A speech prepared but not delivered.},
  keywords  = {caste, India, Dalit},
}

@book{phule1873,
  title  = {Gulamgiri},
  author = {Phule, Jotirao},
  year   = {1873},
}
"""


def _make_fake_library(entries: list[dict]) -> MagicMock:
    lib = MagicMock()
    lib.entries = entries
    return lib


def _make_adapter(tmp_path: Path, entries: list[dict]) -> JabRefAdapter:
    """Build a JabRefAdapter with a mocked bibtexparser library."""
    bib = tmp_path / "library.bib"
    bib.write_text(_SAMPLE_BIB, encoding="utf-8")
    with patch(
        "partial_recall.corpus.adapters.jabref.JabRefAdapter._load",
        return_value=_make_fake_library(entries),
    ), patch(
        "partial_recall.corpus.adapters.jabref._require_bibtexparser"
    ):
        return JabRefAdapter(bib_path=bib)


# ---------------------------------------------------------------------------
# Pure helper tests (no bibtexparser dep)
# ---------------------------------------------------------------------------


def test_parse_authors_last_first() -> None:
    creators = _parse_authors("Ambedkar, B. R. and Phule, Jotirao")
    assert len(creators) == 2
    assert creators[0]["last"] == "Ambedkar"
    assert creators[0]["first"] == "B. R."
    assert creators[1]["last"] == "Phule"


def test_parse_authors_first_last() -> None:
    creators = _parse_authors("B. R. Ambedkar")
    assert creators[0]["last"] == "Ambedkar"
    assert creators[0]["first"] == "B. R."


def test_parse_authors_empty() -> None:
    assert _parse_authors("") == []


def test_resolve_file_links_no_match(tmp_path: Path) -> None:
    assert _resolve_file_links("", tmp_path) == []


def test_resolve_file_links_finds_existing_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    field = f"::{pdf}:PDF"
    result = _resolve_file_links(field, tmp_path)
    assert result == [pdf]


def test_resolve_file_links_ignores_missing(tmp_path: Path) -> None:
    field = ":/nonexistent/path.pdf:PDF"
    assert _resolve_file_links(field, tmp_path) == []


def test_resolve_file_links_ignores_non_pdf(tmp_path: Path) -> None:
    doc = tmp_path / "paper.docx"
    doc.write_bytes(b"PK\x03\x04")
    field = f"::{doc}:DOCX"
    assert _resolve_file_links(field, tmp_path) == []


def test_resolve_file_links_no_description_prefix(tmp_path: Path) -> None:
    # :path:type format (no empty description field) — must still find the PDF
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    field = f":{pdf}:PDF"
    result = _resolve_file_links(field, tmp_path)
    assert result == [pdf]


def test_resolve_file_links_multi_link(tmp_path: Path) -> None:
    # Multiple entries separated by ; — both must be found
    pdf1 = tmp_path / "a.pdf"
    pdf2 = tmp_path / "b.pdf"
    pdf1.write_bytes(b"%PDF-1.4")
    pdf2.write_bytes(b"%PDF-1.4")
    field = f"::{pdf1}:PDF;::{pdf2}:PDF"
    result = _resolve_file_links(field, tmp_path)
    assert set(result) == {pdf1, pdf2}


# ---------------------------------------------------------------------------
# Adapter with mocked library
# ---------------------------------------------------------------------------


_ENTRIES = [
    {
        "ID": "ambedkar1936",
        "ENTRYTYPE": "article",
        "title": "{Annihilation of Caste}",
        "author": "Ambedkar, B. R.",
        "year": "1936",
        "abstract": "A speech prepared but not delivered.",
    },
    {
        "ID": "phule1873",
        "ENTRYTYPE": "book",
        "title": "{Gulamgiri}",
        "author": "Phule, Jotirao",
        "year": "1873",
    },
]


def test_list_items_returns_one_per_entry(tmp_path: Path) -> None:
    adapter = _make_adapter(tmp_path, _ENTRIES)
    items = list(adapter.list_items())
    assert len(items) == 2
    adapter.close()


def test_list_items_corpus_is_jabref(tmp_path: Path) -> None:
    adapter = _make_adapter(tmp_path, _ENTRIES)
    items = list(adapter.list_items())
    assert all(i.corpus == "jabref" for i in items)
    adapter.close()


def test_list_items_title_strips_braces(tmp_path: Path) -> None:
    adapter = _make_adapter(tmp_path, _ENTRIES)
    items = list(adapter.list_items())
    titles = {i.title for i in items}
    assert "Annihilation of Caste" in titles
    adapter.close()


def test_list_items_abstract_populated(tmp_path: Path) -> None:
    adapter = _make_adapter(tmp_path, _ENTRIES)
    items = {i.corpus_ref: i for i in adapter.list_items()}
    assert items["ambedkar1936"].abstract == "A speech prepared but not delivered."
    adapter.close()


def test_list_items_no_abstract_is_none(tmp_path: Path) -> None:
    adapter = _make_adapter(tmp_path, _ENTRIES)
    items = {i.corpus_ref: i for i in adapter.list_items()}
    assert items["phule1873"].abstract is None
    adapter.close()


def test_item_key_stable(tmp_path: Path) -> None:
    adapter = _make_adapter(tmp_path, _ENTRIES)
    items1 = list(adapter.list_items())
    items2 = list(adapter.list_items())
    assert items1[0].item_key == items2[0].item_key
    adapter.close()


def test_count_items(tmp_path: Path) -> None:
    adapter = _make_adapter(tmp_path, _ENTRIES)
    assert adapter.count_items() == 2
    adapter.close()


def test_get_sources_yields_abstract_when_present(tmp_path: Path) -> None:
    adapter = _make_adapter(tmp_path, _ENTRIES)
    items = {i.corpus_ref: i for i in adapter.list_items()}
    sources = list(adapter.get_sources(items["ambedkar1936"]))
    assert any(s.source_type == "abstract" for s in sources)
    adapter.close()


def test_get_sources_no_abstract_yields_nothing(tmp_path: Path) -> None:
    adapter = _make_adapter(tmp_path, _ENTRIES)
    items = {i.corpus_ref: i for i in adapter.list_items()}
    sources = list(adapter.get_sources(items["phule1873"]))
    assert sources == []
    adapter.close()


def test_get_text_abstract(tmp_path: Path) -> None:
    adapter = _make_adapter(tmp_path, _ENTRIES)
    items = {i.corpus_ref: i for i in adapter.list_items()}
    item = items["ambedkar1936"]
    sources = list(adapter.get_sources(item))
    text = adapter.get_text(item, sources[0])
    assert text == "A speech prepared but not delivered."
    adapter.close()


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_missing_bib_raises(tmp_path: Path) -> None:
    with (
        patch("partial_recall.corpus.adapters.jabref._require_bibtexparser"),
        pytest.raises(CorpusUnavailableError, match="not found"),
    ):
        JabRefAdapter(bib_path=tmp_path / "nonexistent.bib")


def test_missing_bibtexparser_raises(tmp_path: Path) -> None:
    bib = tmp_path / "library.bib"
    bib.write_text(_SAMPLE_BIB, encoding="utf-8")
    with patch(
        "partial_recall.corpus.adapters.jabref._require_bibtexparser",
        side_effect=JabRefAdapterError("bibtexparser not installed"),
    ), pytest.raises(JabRefAdapterError, match="bibtexparser"):
        JabRefAdapter(bib_path=bib)
