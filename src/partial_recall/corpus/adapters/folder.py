"""FolderAdapter — index a directory tree of documents.

The answer to "is partial-recall just for Zotero users?" — no. Point it
at any directory and it walks recursively, picking up text-bearing
files by extension.

v0.2.0 scope:
  * PDF (via the existing pypdf extractor)
  * Plain text (.txt)
  * Markdown (.md / .markdown) — extracted as raw text, no rendering
  * EPUB and DOCX are *advertised* extensions but currently raise
    UnsupportedExtension; their adapters need extra dependencies
    (ebooklib, python-docx) and ship later. Files with these
    extensions are skipped with a structured log warning, not crashed.

The adapter respects an optional `.partial-recallignore` file at the
root of each configured path: gitignore-style globs, one per line,
hash-comments allowed.

Item identity: SHA-256 of the absolute path, truncated to 12 hex chars
plus the filename stem (which keeps item_keys readable in CLI output
without sacrificing uniqueness). corpus_ref holds the full path for
debugging / external open commands.
"""

from __future__ import annotations

import fnmatch
import hashlib
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import structlog

from partial_recall.corpus.types import Item, ItemKind, Source
from partial_recall.errors import CorpusUnavailableError, PartialRecallError
from partial_recall.extract.pdf import PdfExtractionError, extract_pdf_text

log = structlog.get_logger(__name__)


# Extensions we have working extractors for, vs. extensions we know
# about but haven't wired the extractor for yet.
_TEXT_EXTENSIONS = frozenset({".txt", ".md", ".markdown"})
_PDF_EXTENSIONS = frozenset({".pdf"})
_DEFERRED_EXTENSIONS = frozenset({".epub", ".docx"})
_KNOWN_EXTENSIONS = _TEXT_EXTENSIONS | _PDF_EXTENSIONS | _DEFERRED_EXTENSIONS


class FolderAdapterError(PartialRecallError):
    """FolderAdapter-specific failure."""


def _stable_item_key(path: Path) -> str:
    """A short, stable, readable identifier for a file.

    The first 12 hex chars of the SHA-256 of the absolute path make the
    key globally unique within a corpus and stable across runs. We
    append the file's stem (lowercased, alnum-only, length-capped) so
    a human reading CLI output sees recognisable identifiers.
    """
    h = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    stem = "".join(c if c.isalnum() else "_" for c in path.stem.lower())[:30]
    return f"{h}-{stem}" if stem else h


def _read_ignorefile(path: Path) -> list[str]:
    """Return non-blank, non-comment lines from a .partial-recallignore."""
    if not path.exists():
        return []
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _matches_any(rel: str, patterns: list[str]) -> bool:
    """Match a relative path against gitignore-ish globs (fnmatch semantics)."""
    if not patterns:
        return False
    for pat in patterns:
        # Strip leading "./" since fnmatch doesn't know what to do with it.
        p = pat.lstrip("./")
        if fnmatch.fnmatch(rel, p):
            return True
        # gitignore-style "dir/" should match anything under dir/.
        if p.endswith("/") and (rel.startswith(p) or rel == p.rstrip("/")):
            return True
    return False


class FolderAdapter:
    """Recursive read-only corpus adapter for a directory tree."""

    name = "folder"
    version = "1"
    capabilities = frozenset({ItemKind.TEXT, ItemKind.METADATA})

    def __init__(
        self,
        *,
        roots: list[Path],
        recursive: bool = True,
        extensions: frozenset[str] | None = None,
    ) -> None:
        if not roots:
            raise CorpusUnavailableError(
                "FolderAdapter needs at least one root directory in `roots`."
            )
        self.roots = [Path(r).resolve() for r in roots]
        for r in self.roots:
            if not r.exists():
                raise CorpusUnavailableError(f"folder root not found: {r}")
            if not r.is_dir():
                raise CorpusUnavailableError(f"folder root is not a directory: {r}")
        self.recursive = recursive
        # Default to text-only + pdf so v0.2.0 doesn't promise extractors
        # it doesn't have. EPUB/DOCX configured by the user still resolve
        # to "skip" until their extractors ship.
        self.extensions = (
            frozenset(ext.lower() for ext in extensions)
            if extensions is not None
            else (_TEXT_EXTENSIONS | _PDF_EXTENSIONS)
        )
        # Pre-load ignore patterns per root.
        self._ignore_patterns: dict[Path, list[str]] = {
            r: _read_ignorefile(r / ".partial-recallignore") for r in self.roots
        }

    def close(self) -> None:
        return None

    # ------------------------------------------------------------------
    # CorpusAdapter Protocol
    # ------------------------------------------------------------------

    def count_items(self, since: datetime | None = None) -> int | None:
        return sum(1 for _ in self._walk())

    def list_items(self, since: datetime | None = None) -> Iterator[Item]:
        for path in self._walk():
            try:
                stat = path.stat()
            except OSError as e:
                log.warning("folder.adapter.stat_failed", path=str(path), error=str(e))
                continue
            mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            yield Item(
                item_key=_stable_item_key(path),
                corpus="folder",
                item_type="file",
                title=path.stem,
                date=mtime,
                creators=[],
                abstract=None,
                metadata_hash=hashlib.sha256(
                    f"{path.resolve()}|{stat.st_mtime}|{stat.st_size}".encode()
                ).hexdigest(),
                corpus_ref=str(path.resolve()),
            )

    def get_sources(self, item: Item) -> Iterator[Source]:
        if not item.corpus_ref:
            return
        yield Source(
            source_type="file",
            source_ref=item.corpus_ref,
            kind=ItemKind.TEXT,
        )

    def get_text(self, item: Item, source: Source) -> str | None:
        if source.source_type != "file" or not source.source_ref:
            return None
        path = Path(source.source_ref)
        if not path.exists():
            log.warning("folder.adapter.missing_file", path=str(path))
            return None
        ext = path.suffix.lower()
        if ext in _PDF_EXTENSIONS:
            try:
                return extract_pdf_text(path)
            except PdfExtractionError as e:
                log.warning("folder.adapter.pdf_failed", path=str(path), error=str(e))
                return None
        if ext in _TEXT_EXTENSIONS:
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                log.warning("folder.adapter.read_failed", path=str(path), error=str(e))
                return None
        if ext in _DEFERRED_EXTENSIONS:
            log.info(
                "folder.adapter.extension_deferred",
                path=str(path),
                extension=ext,
                note="extractor lands in a later release; file skipped",
            )
            return None
        log.info("folder.adapter.unknown_extension", path=str(path), extension=ext)
        return None

    def get_image(self, item: Item, source: Source) -> bytes | None:
        return None  # v0.4.0+

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _walk(self) -> Iterator[Path]:
        for root in self.roots:
            patterns = self._ignore_patterns.get(root, [])
            candidates = root.rglob("*") if self.recursive else root.glob("*")
            for p in candidates:
                if not p.is_file():
                    continue
                ext = p.suffix.lower()
                if ext not in self.extensions:
                    continue
                try:
                    rel = p.relative_to(root)
                except ValueError:
                    rel = p
                if _matches_any(str(rel), patterns):
                    continue
                # Hide dotfiles and dot-directories by default — they're
                # almost always tooling, not corpus.
                if any(part.startswith(".") for part in rel.parts):
                    continue
                yield p
