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
    # pypdf can raise inside reader.pages iteration itself (e.g. "Cannot
    # find Root object in pdf" for a PDF missing its Catalog). Wrap the
    # whole iteration so one severely-malformed PDF doesn't kill an
    # indexing run mid-batch.
    pages: list[str] = []
    try:
        page_iter = iter(reader.pages)
    except (PdfReadError, PdfStreamError) as e:
        raise PdfExtractionError(
            f"cannot enumerate pages of {path}: {e}"
        ) from e
    while True:
        try:
            page = next(page_iter)
        except StopIteration:
            break
        except (PdfReadError, PdfStreamError):
            # Cross-ref recovery exhausted; stop reading this PDF, keep
            # whatever pages we already got.
            break
        except Exception:  # noqa: BLE001 — pypdf can throw arbitrary internals
            break
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — per-page extraction can also fail
            text = ""
        pages.append(text)
    return pages
