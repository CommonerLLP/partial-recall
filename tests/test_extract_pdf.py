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
