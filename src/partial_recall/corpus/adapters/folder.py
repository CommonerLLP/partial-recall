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
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from partial_recall.store.vector_store import VectorStore

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


def _root_id(root: Path) -> str:
    """Stable identifier for a configured root: survives reordering.

    'r' + first 10 hex of SHA-256 of the resolved path. The 'r' marker
    cannot collide with the legacy numeric root-index prefix or with an
    absolute path, so every source_ref format stays distinguishable.
    """
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
    return f"r{digest[:10]}"




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
        # Stable per-root identifier: source_ref must not depend on the
        # ORDER of `roots` in config — reordering used to orphan every
        # chunk and re-embed the corpus. The "r" marker keeps the id
        # distinguishable from the legacy numeric root-index prefix.
        self._roots_by_id: dict[str, Path] = {
            _root_id(r): r for r in self.roots
        }
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
        # Emit "{root_id}:{rel_posix}" so source_ref is portable,
        # unambiguous with multiple roots that share filenames (issue
        # #23), and stable when config roots are reordered. Fall back to
        # the absolute path only for files that fall outside every
        # configured root (edge case; shouldn't happen in normal use).
        for root in self.roots:
            try:
                rel = abs_path.relative_to(root).as_posix()
                yield Source(
                    source_type="file",
                    source_ref=f"{_root_id(root)}:{rel}",
                    kind=ItemKind.TEXT,
                )
                return
            except ValueError:
                continue
        yield Source(
            source_type="file",
            source_ref=str(abs_path),
            kind=ItemKind.TEXT,
        )

    def _resolve_source_ref(self, source_ref: str) -> Path | None:
        """Return an absolute Path for source_ref.

        Accepts every format ever written to a store:
        - "{root_id}:{rel_posix}"   — current stable format
        - "{root_idx}:{rel_posix}"  — legacy positional format (pre-stable-ids)
        - absolute path             — legacy rows indexed before issue #23
        - bare relative path        — intermediate format (should not occur
                                      in production, but handled defensively)
        """
        p = Path(source_ref)
        if p.is_absolute():
            return p if p.exists() else None
        if ":" in source_ref:
            prefix, _, rel = source_ref.partition(":")
            root = self._roots_by_id.get(prefix)
            if root is not None:
                candidate = root / rel
                return candidate if candidate.exists() else None
            if prefix.isdigit():
                idx = int(prefix)
                if idx < len(self.roots):
                    candidate = self.roots[idx] / rel
                    return candidate if candidate.exists() else None
        # Bare relative path — scan all roots (defensive fallback).
        for root in self.roots:
            candidate = root / source_ref
            if candidate.exists():
                return candidate
        return None

    def migrate_source_refs(self, store: VectorStore) -> dict[str, int]:
        """Rewrite legacy source_refs to the stable root-id format.

        Optional adapter hook, called by run_indexing before walking.
        Handles both legacy formats: positional "{idx}:{rel}" (mapped
        through the CURRENT root order — the same mapping the old lookup
        used) and absolute paths that fall under a configured root.
        Rows whose rewrite target already exists are merged by the store
        (past drift created those duplicates); their vectors survive on
        the merged row. Idempotent: current-format refs are untouched,
        and unmappable refs (absolute paths outside every configured
        root) are left alone and counted as skipped.
        """
        counts = {"rewritten": 0, "merged": 0, "skipped": 0}
        for row in store.iter_chunk_refs(corpus=self.name):
            new_ref = self._legacy_ref_to_stable(row["source_ref"])
            if new_ref == row["source_ref"]:
                continue
            if new_ref is None:
                counts["skipped"] += 1
                continue
            outcome = store.rewrite_chunk_source_ref(
                chunk_id=row["chunk_id"],
                corpus=self.name,
                new_source_ref=new_ref,
            )
            counts[outcome] += 1
        if counts["rewritten"] or counts["merged"] or counts["skipped"]:
            log.info("folder.adapter.source_refs_migrated", **counts)
        return counts

    def _legacy_ref_to_stable(self, source_ref: str) -> str | None:
        """Map a legacy source_ref to the stable format; None if unmappable."""
        if any(source_ref.startswith(f"{rid}:") for rid in self._roots_by_id):
            return source_ref  # already stable
        p = Path(source_ref)
        if p.is_absolute():
            for root in self.roots:
                try:
                    rel = p.relative_to(root).as_posix()
                except ValueError:
                    continue
                return f"{_root_id(root)}:{rel}"
            return None  # outside every configured root — leave untouched
        if ":" in source_ref:
            prefix, _, rel = source_ref.partition(":")
            if prefix.isdigit() and int(prefix) < len(self.roots):
                return f"{_root_id(self.roots[int(prefix)])}:{rel}"
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
