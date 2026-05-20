"""DOCX text extractor (v0.3.0).

Word documents (.docx) are the primary writing format for many
humanities scholars. This extractor reads the document XML directly
using stdlib (zipfile + xml.etree) — no python-docx dependency needed.

.docx files are zip archives. The text lives in word/document.xml as
<w:t> elements. We walk those elements in document order, inserting
paragraph breaks at <w:p> boundaries so the extracted text reads
naturally as prose.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def extract_docx_text(path: Path) -> str | None:
    """Return plain text from a .docx file, or None on failure.

    Reads word/document.xml from the zip archive and extracts text
    from <w:t> elements, inserting newlines at paragraph (<w:p>)
    boundaries.
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                log.warning("docx.extractor.no_document_xml", path=str(path))
                return None
            raw = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        log.warning("docx.extractor.failed", path=str(path), error=str(e))
        return None

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        log.warning("docx.extractor.parse_failed", path=str(path), error=str(e))
        return None

    paragraphs: list[str] = []
    for para in root.iter(f"{{{_W_NS}}}p"):
        texts = [
            t.text or ""
            for t in para.iter(f"{{{_W_NS}}}t")
        ]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)

    return "\n\n".join(paragraphs) or None
