"""PDF text extraction via pypdf.

v0.0.1 = no OCR. Image-only PDFs yield empty text. Encrypted PDFs raise.
v0.3.0+ will add OCR (Tesseract / Kraken / Transkribus).
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

from partial_recall.errors import PartialRecallError


class PdfExtractionError(PartialRecallError):
    """Raised when a PDF cannot be opened or read."""


def extract_pdf_text(path: Path) -> str:
    """Return concatenated text from all pages of a PDF.

    Empty pages contribute nothing. Returns empty string for an image-only PDF.
    """
    pages = extract_pdf_text_by_page(path)
    return "\n\n".join(p for p in pages if p)


def extract_pdf_text_by_page(path: Path) -> list[str]:
    """Return a list of strings, one per page."""
    if not path.exists():
        raise PdfExtractionError(f"PDF not found: {path}")
    try:
        reader = PdfReader(str(path))
    except (PdfReadError, PdfStreamError, OSError) as e:
        raise PdfExtractionError(f"cannot read PDF {path}: {e}") from e
    if reader.is_encrypted:
        raise PdfExtractionError(
            f"PDF is encrypted (no decrypt support in v0.0.1): {path}"
        )
    pages: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — pypdf can throw various internal errors
            text = ""
        pages.append(text)
    return pages
