"""Tests for PDF text extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from partial_recall.extract.pdf import (
    PdfExtractionError,
    extract_pdf_text,
    extract_pdf_text_by_page,
)


def _fixture(fixtures_dir: Path, name: str) -> Path:
    return fixtures_dir / "sample_pdfs" / name


def test_extract_english_pdf_yields_known_text(fixtures_dir: Path) -> None:
    text = extract_pdf_text(_fixture(fixtures_dir, "english.pdf"))
    assert "library policy" in text.lower()
    assert "nplis" in text.lower()


def test_extract_multipage_yields_text_from_all_pages(fixtures_dir: Path) -> None:
    text = extract_pdf_text(_fixture(fixtures_dir, "multipage.pdf"))
    assert "chattopadhyaya" in text.lower()
    assert "national knowledge commission" in text.lower()


def test_extract_by_page_returns_per_page_list(fixtures_dir: Path) -> None:
    pages = extract_pdf_text_by_page(_fixture(fixtures_dir, "multipage.pdf"))
    assert len(pages) == 2
    assert "chattopadhyaya" in pages[0].lower()
    assert "national knowledge commission" in pages[1].lower()


def test_extract_empty_pdf_returns_empty_string(fixtures_dir: Path) -> None:
    text = extract_pdf_text(_fixture(fixtures_dir, "empty.pdf"))
    assert text.strip() == ""


def test_extract_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PdfExtractionError, match="not found"):
        extract_pdf_text(tmp_path / "nonexistent.pdf")


def test_extract_non_pdf_raises(tmp_path: Path) -> None:
    bad = tmp_path / "not-a-pdf.pdf"
    bad.write_text("definitely not a PDF", encoding="utf-8")
    with pytest.raises(PdfExtractionError):
        extract_pdf_text(bad)


# ---------------------------------------------------------------------------
# Regression: malformed PDF that raises during reader.pages iteration
# (e.g. missing /Root Catalog object) must NOT propagate out and kill
# the indexing run. The 2026-05-18 indexing crash exposed this gap.
# ---------------------------------------------------------------------------


def test_extract_pdf_with_no_root_object_does_not_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When pypdf raises PdfReadError during `iter(reader.pages)` (the
    'Cannot find Root object in pdf' class), extract_pdf_text_by_page
    must raise PdfExtractionError — which `ZoteroAdapter.get_text`
    already catches — rather than letting an internal pypdf exception
    propagate up the call stack and crash the indexer."""
    from pypdf.errors import PdfReadError

    # Build a file that exists (passes the path check). Content doesn't
    # matter — we replace the PdfReader so we can deterministically
    # reproduce the failure mode without crafting a malformed PDF.
    bad_pdf = tmp_path / "no_root.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\n%placeholder\n")

    class _BadPages:
        def __iter__(self):  # noqa: D401
            raise PdfReadError("Cannot find Root object in pdf")

    class _FakeReader:
        is_encrypted = False
        pages = _BadPages()

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(
        "partial_recall.extract.pdf.PdfReader",
        _FakeReader,
    )

    with pytest.raises(PdfExtractionError, match="enumerate"):
        extract_pdf_text_by_page(bad_pdf)


def test_extract_pdf_keeps_pages_before_pypdf_mid_iter_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If pypdf can enumerate the first page but raises on the second,
    we keep page 1's text and stop cleanly — better than losing
    everything we'd already successfully extracted."""
    from pypdf.errors import PdfReadError

    bad_pdf = tmp_path / "mid_iter_fail.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\n%placeholder\n")

    class _OkPage:
        def extract_text(self) -> str:
            return "first page text — recovered before the failure"

    def _gen_pages():
        yield _OkPage()
        raise PdfReadError("xref recovery exhausted mid-iteration")

    class _PagesProxy:
        def __iter__(self):
            return _gen_pages()

    class _FakeReader:
        is_encrypted = False
        pages = _PagesProxy()

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(
        "partial_recall.extract.pdf.PdfReader",
        _FakeReader,
    )

    pages = extract_pdf_text_by_page(bad_pdf)
    assert len(pages) == 1
    assert "recovered before the failure" in pages[0]


def test_extract_pdf_zotero_adapter_returns_none_on_root_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end behaviour the indexer relies on: extract_pdf_text
    raises PdfExtractionError on a fundamentally-broken PDF, and the
    ZoteroAdapter caller's try/except converts that to None (= 'no
    text for this source, skip and continue')."""
    from pypdf.errors import PdfReadError

    bad_pdf = tmp_path / "no_root.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\n%placeholder\n")

    class _BadPages:
        def __iter__(self):
            raise PdfReadError("Cannot find Root object in pdf")

    class _FakeReader:
        is_encrypted = False
        pages = _BadPages()

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(
        "partial_recall.extract.pdf.PdfReader",
        _FakeReader,
    )

    # Simulate the adapter's pattern: try/except returns None.
    try:
        text: str | None = extract_pdf_text(bad_pdf)
    except PdfExtractionError:
        text = None
    assert text is None
