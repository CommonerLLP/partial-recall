"""EPUB text extractor using stdlib only (no ebooklib dep).

Reads the EPUB zip archive and extracts text from HTML/XHTML content
files. Strips tags, preserves paragraph breaks. Used by FolderAdapter
and CalibreAdapter.
"""

from __future__ import annotations

import html.parser
import zipfile
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "br"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def extract_epub_text(path: Path) -> str | None:
    """Return plain text from an EPUB file, or None on failure.

    Extracts all HTML/XHTML content files in the archive and
    concatenates them in filename order (which approximates reading
    order for most EPUBs). Does not parse the OPF spine — good enough
    for search indexing where order matters less than coverage.
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            content_files = sorted(
                n for n in names
                if n.endswith((".html", ".xhtml", ".htm"))
                and not n.startswith("__MACOSX")
            )
            parts: list[str] = []
            for name in content_files:
                try:
                    raw = zf.read(name).decode("utf-8", errors="replace")
                    extractor = _TextExtractor()
                    extractor.feed(raw)
                    text = "".join(extractor.parts).strip()
                    if text:
                        parts.append(text)
                except Exception as e:  # noqa: BLE001
                    log.warning("epub.extractor.file_failed", file=name, error=str(e))
        return "\n\n".join(parts) or None
    except (zipfile.BadZipFile, OSError) as e:
        log.warning("epub.extractor.failed", path=str(path), error=str(e))
        return None
