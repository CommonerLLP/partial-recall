"""PDF text extraction via PyMuPDF.

v0.0.1 = no OCR. Image-only PDFs yield empty text. Encrypted PDFs raise.
v0.3.0+ will add OCR (Tesseract / Kraken / Transkribus).
"""

from __future__ import annotations

from pathlib import Path

import fitz

from partial_recall.errors import PartialRecallError


class PdfExtractionError(PartialRecallError):
    """Raised when a PDF cannot be opened or read."""


# Which reader `extract_pdf_text` uses. Set once at startup from config, so
# the five adapter call sites need no plumbing. "pymupdf" is the default and
# the only backend with no extra dependency.
_BACKEND = "pymupdf"


def set_pdf_backend(name: str) -> None:
    """Select the PDF reader for this process."""
    global _BACKEND
    if name not in ("pymupdf", "docling"):
        raise ValueError(f"unknown pdf backend: {name!r}")
    _BACKEND = name


def get_pdf_backend() -> str:
    """Report the PDF reader this process uses."""
    return _BACKEND


def extract_pdf_text(path: Path) -> str:
    """Return the text of a PDF using the configured backend.

    The pymupdf backend concatenates pages; empty pages contribute nothing,
    and an image-only PDF yields an empty string. The docling backend returns
    Markdown with tables and reading order preserved.
    """
    if _BACKEND == "docling":
        from partial_recall.extract.docling_pdf import extract_pdf_text_docling

        return extract_pdf_text_docling(path)
    pages = extract_pdf_text_by_page(path)
    return "\n\n".join(p for p in pages if p)


def extract_pdf_text_by_page(path: Path) -> list[str]:
    """Return a list of strings, one per page, extracted in reading order."""
    if not path.exists():
        raise PdfExtractionError(f"PDF not found: {path}")
    
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise PdfExtractionError(f"cannot read PDF {path}: {e}") from e
        
    if doc.is_encrypted:
        doc.close()
        raise PdfExtractionError(
            f"PDF is encrypted (no decrypt support in v0.0.1): {path}"
        )

    pages: list[str] = []
    try:
        for page in doc:
            try:
                # Use block extraction to preserve column reading order
                blocks = page.get_text("blocks")
                # Filter text blocks (block_type == 0)
                text_blocks = [b for b in blocks if b[6] == 0]
                
                # Sort by column (binning x0 to nearest 100 points) then y0
                text_blocks.sort(key=lambda b: (round(b[0] / 100), b[1]))
                
                text = "\n".join(b[4].strip() for b in text_blocks)
                pages.append(text)
            except Exception:
                # Per-page extraction can fail, keep going
                pages.append("")
    finally:
        doc.close()

    return pages
