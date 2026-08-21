"""Structured PDF extraction via Docling (optional backend).

PyMuPDF reads a page as positioned text blocks. This module reads a page as
a document: Docling recovers layout, reading order, and table structure, then
serialises to Markdown, so a table survives as a table instead of collapsing
into interleaved cell text. That matters for scanned and multi-column
government PDFs, where the block reader produces plausible but scrambled prose.

Docling is an optional extra, and deliberately so. It pulls torch,
torchvision, and opencv, and it pins an older `transformers` than
`sentence-transformers` wants. Install it in its own environment:

    pip install "partial-recall[docling]"

The import is lazy. Nothing here loads unless the backend is selected.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

from partial_recall.extract.pdf import PdfExtractionError

log = structlog.get_logger(__name__)

_INSTALL_HINT = (
    "The docling backend needs the docling package. "
    'Install it with: pip install "partial-recall[docling]" — '
    "note it downgrades transformers, so keep it out of an environment "
    "running the multilingual extra."
)


@lru_cache(maxsize=1)
def _converter() -> Any:
    """Build the Docling converter once. Model load is slow."""
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as e:
        raise PdfExtractionError(_INSTALL_HINT) from e
    return DocumentConverter()


def docling_available() -> bool:
    """Report whether the docling package can be imported."""
    try:
        import docling  # noqa: F401
    except ImportError:
        return False
    return True


def extract_pdf_text_docling(path: Path) -> str:
    """Return Markdown text for a PDF, with tables and reading order kept.

    Raises PdfExtractionError when docling is absent or the file cannot be
    read, so callers handle it exactly as they handle the PyMuPDF backend.
    """
    if not path.exists():
        raise PdfExtractionError(f"PDF not found: {path}")
    try:
        result = _converter().convert(str(path))
        return str(result.document.export_to_markdown())
    except PdfExtractionError:
        raise
    except Exception as e:
        raise PdfExtractionError(f"docling cannot read PDF {path}: {e}") from e
