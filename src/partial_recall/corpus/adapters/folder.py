"""FolderAdapter — index a directory tree of documents.

The answer to "is partial-recall just for Zotero users?" — no. Point it
at any directory and it walks recursively, picking up text-bearing
files by extension.

Supported formats:
  * PDF (via pypdf extractor)
  * Plain text (.txt)
  * Markdown (.md / .markdown)
  * EPUB (stdlib zip+html parser — no extra dep)
  * DOCX / Word documents (stdlib zip+xml parser — no extra dep)

The adapter respects an optional `.partial-recallignore` file at the
root of each configured path: gitignore-style globs, one per line,
hash-comments allowed.

Item identity: SHA-256 of the absolute path, truncated to 12 hex chars
plus the filename stem (which keeps item_keys readable in CLI output
without sacrificing uniqueness). corpus_ref holds the full path for
debugging / external open commands.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import structlog

from partial_recall.corpus.adapters._shared import matches_any, read_ignorefile, stable_item_key
from partial_recall.corpus.types import Item, ItemKind, Source
from partial_recall.errors import CorpusUnavailableError, PartialRecallError
from partial_recall.extract.docx import extract_docx_text
from partial_recall.extract.epub import extract_epub_text
from partial_recall.extract.pdf import PdfExtractionError, extract_pdf_text

log = structlog.get_logger(__name__)


_TEXT_EXTENSIONS = frozenset({".txt", ".md", ".markdown"})
_PDF_EXTENSIONS = frozenset({".pdf"})
_EPUB_EXTENSIONS = frozenset({".epub"})
_DOCX_EXTENSIONS = frozenset({".docx"})
_KNOWN_EXTENSIONS = _TEXT_EXTENSIONS | _PDF_EXTENSIONS | _EPUB_EXTENSIONS | _DOCX_EXTENSIONS


class FolderAdapterError(PartialRecallError):
    """FolderAdapter-specific failure."""




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
            r: read_ignorefile(r / ".partial-recallignore") for r in self.roots
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
                item_key=stable_item_key(path),
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
        abs_path = Path(item.corpus_ref)
        # Emit a POSIX-relative path so source_ref is portable across
        # machines and folder moves.  Fall back to the absolute path only
        # if the file does not sit under any configured root (shouldn't
        # happen in normal operation, but guards against edge cases).
        rel: str | None = None
        for root in self.roots:
            try:
                rel = abs_path.relative_to(root).as_posix()
                break
            except ValueError:
                continue
        yield Source(
            source_type="file",
            source_ref=rel if rel is not None else str(abs_path),
            kind=ItemKind.TEXT,
        )

    def _resolve_source_ref(self, source_ref: str) -> Path | None:
        """Return an absolute Path for source_ref (relative or legacy absolute)."""
        p = Path(source_ref)
        if p.is_absolute():
            return p if p.exists() else None
        for root in self.roots:
            candidate = root / p
            if candidate.exists():
                return candidate
        return None

    def get_text(self, item: Item, source: Source) -> str | None:
        if source.source_type != "file" or not source.source_ref:
            return None
        path = self._resolve_source_ref(source.source_ref)
        if path is None:
            log.warning("folder.adapter.missing_file", source_ref=source.source_ref)
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
        if ext in _EPUB_EXTENSIONS:
            return extract_epub_text(path)
        if ext in _DOCX_EXTENSIONS:
            return extract_docx_text(path)
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
                # Normalise to forward-slash form for ignore-pattern
                # matching: gitignore-style globs are POSIX. Without
                # this, `drafts/` does not match `drafts\foo.md` on
                # Windows.
                rel_posix = rel.as_posix() if isinstance(rel, Path) else str(rel)
                if matches_any(rel_posix, patterns):
                    continue
                # Hide dotfiles and dot-directories by default — they're
                # almost always tooling, not corpus.
                if any(part.startswith(".") for part in rel.parts):
                    continue
                yield p
