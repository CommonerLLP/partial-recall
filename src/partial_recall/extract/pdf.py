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


def extract_pdf_text(path: Path) -> str:
    """Return concatenated text from all pages of a PDF.

    Empty pages contribute nothing. Returns empty string for an image-only PDF.
    """
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
