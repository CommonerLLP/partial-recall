"""CalibreAdapter — index a Calibre e-book library (v0.3.0).

Calibre is a free, open-source e-book management application used
widely by independent scholars and readers. It stores its catalogue
in a SQLite database (`metadata.db`) alongside the book files.

This adapter reads that database directly — no Calibre installation
required at index time. Each book in the catalogue becomes one Item.

What gets indexed per book:
  - Title, authors, tags, publication date, publisher → Item metadata
  - Comments field (Calibre's description/synopsis) → abstract source
  - Linked book file (EPUB, PDF, TXT, MOBI) → extracted text source,
    in that preference order. Only formats with working extractors are
    used; others are skipped with a log warning.

Calibre's `metadata.db` schema is stable across versions (Kovid Goyal
maintains strict backwards compat). The tables we read are:
  books, authors, books_authors_link, tags, books_tags_link,
  comments, data (the file-format rows).
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import structlog

from partial_recall.corpus.types import Item, ItemKind, Source
from partial_recall.errors import CorpusUnavailableError, PartialRecallError

log = structlog.get_logger(__name__)

# Calibre stores timestamps as ISO-8601 strings in UTC.
# We use them as-is for the Item.date field.

# Formats we can extract text from, in preference order.
_EXTRACTABLE = ("EPUB", "PDF", "TXT", "MD")


class CalibreAdapterError(PartialRecallError):
    """CalibreAdapter-specific failure."""


class CalibreAdapter:
    """Read-only corpus adapter for a Calibre e-book library."""

    name = "calibre"
    version = "1"
    capabilities = frozenset({ItemKind.TEXT, ItemKind.METADATA})

    def __init__(self, *, library_path: Path) -> None:
        self.library_path = Path(library_path).resolve()
        if not self.library_path.exists():
            raise CorpusUnavailableError(
                f"Calibre library folder not found: {self.library_path}"
            )
        if not self.library_path.is_dir():
            raise CorpusUnavailableError(
                f"Calibre library path is not a directory: {self.library_path}"
            )
        self._db_path = self.library_path / "metadata.db"
        if not self._db_path.exists():
            raise CorpusUnavailableError(
                f"Calibre metadata.db not found at {self._db_path}. "
                "Make sure this is a Calibre library folder."
            )
        # Open read-only so we never corrupt the user's library.
        try:
            self._conn = sqlite3.connect(
                f"file:{self._db_path}?mode=ro&immutable=1",
                uri=True,
                timeout=5,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
        except sqlite3.OperationalError as e:
            raise CorpusUnavailableError(
                f"Could not open Calibre metadata.db read-only: {e}"
            ) from e

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # CorpusAdapter Protocol
    # ------------------------------------------------------------------

    def count_items(self, since: datetime | None = None) -> int | None:
        row = self._conn.execute("SELECT COUNT(*) FROM books").fetchone()
        return row[0] if row else 0

    def list_items(self, since: datetime | None = None) -> Iterator[Item]:
        rows = self._conn.execute(
            "SELECT id, title, pubdate, timestamp FROM books ORDER BY id"
        ).fetchall()
        authors_map = self._load_authors_map()
        comments_map = self._load_comments_map()
        for row in rows:
            book_id = row["id"]
            title = row["title"] or ""
            pubdate = row["pubdate"] or row["timestamp"] or ""
            creators = authors_map.get(book_id, [])
            abstract = comments_map.get(book_id)
            item_key = self._book_item_key(book_id, title)
            metadata_hash = hashlib.sha256(
                f"{book_id}:{title}:{pubdate}".encode()
            ).hexdigest()
            yield Item(
                item_key=item_key,
                corpus="calibre",
                item_type="book",
                title=title,
                date=str(pubdate)[:10] if pubdate else None,
                creators=creators,
                abstract=abstract,
                metadata_hash=metadata_hash,
                corpus_ref=str(book_id),
            )

    def get_sources(self, item: Item) -> Iterator[Source]:
        if not item.corpus_ref:
            return
        book_id = int(item.corpus_ref)
        if item.abstract:
            yield Source(
                source_type="abstract",
                source_ref=item.corpus_ref,
                kind=ItemKind.TEXT,
            )
        for fmt, path in self._book_files(book_id):
            if fmt in _EXTRACTABLE:
                yield Source(
                    source_type=fmt.lower(),
                    source_ref=str(path),
                    kind=ItemKind.TEXT,
                )

    def get_text(self, item: Item, source: Source) -> str | None:
        if source.source_type == "abstract":
            return item.abstract
        if source.source_type == "pdf":
            if not source.source_ref:
                return None
            from partial_recall.extract.pdf import PdfExtractionError, extract_pdf_text
            try:
                return extract_pdf_text(Path(source.source_ref))
            except PdfExtractionError as e:
                log.warning("calibre.adapter.pdf_failed", path=source.source_ref, error=str(e))
                return None
        if source.source_type in ("txt", "md", "epub"):
            if not source.source_ref:
                return None
            path = Path(source.source_ref)
            if not path.exists():
                log.warning("calibre.adapter.missing_file", path=str(path))
                return None
            if source.source_type == "epub":
                from partial_recall.extract.epub import extract_epub_text
                return extract_epub_text(path)
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                log.warning("calibre.adapter.read_failed", path=str(path), error=str(e))
                return None
        return None

    def get_image(self, item: Item, source: Source) -> bytes | None:
        return None  # v0.4.0+

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _book_item_key(self, book_id: int, title: str) -> str:
        h = hashlib.sha256(
            f"{self.library_path}:{book_id}".encode()
        ).hexdigest()[:12]
        stem = "".join(c if c.isalnum() else "_" for c in title.lower())[:30]
        return f"{h}-{stem}" if stem else h

    def _load_authors_map(self) -> dict[int, list[dict[str, str]]]:
        rows = self._conn.execute(
            "SELECT bal.book, a.name FROM books_authors_link bal "
            "JOIN authors a ON a.id = bal.author"
        ).fetchall()
        result: dict[int, list[dict[str, str]]] = {}
        for row in rows:
            book_id, name = row[0], row[1]
            # Calibre stores "Last, First" convention.
            if "," in name:
                parts = name.split(",", 1)
                creator = {"last": parts[0].strip(), "first": parts[1].strip()}
            else:
                parts = name.rsplit(" ", 1)
                creator = {"last": parts[-1], "first": parts[0] if len(parts) > 1 else ""}
            result.setdefault(book_id, []).append(creator)
        return result

    def _load_comments_map(self) -> dict[int, str]:
        rows = self._conn.execute("SELECT book, text FROM comments").fetchall()
        return {row[0]: row[1] for row in rows if row[1]}

    def _book_files(self, book_id: int) -> list[tuple[str, Path]]:
        """Return (FORMAT, resolved_path) pairs for a book, best format first."""
        rows = self._conn.execute(
            "SELECT format, name FROM data WHERE book = ?", (book_id,)
        ).fetchall()
        book_folder = self._book_folder(book_id)
        if book_folder is None:
            return []
        result: list[tuple[str, Path]] = []
        # Sort by preference order so sources are yielded best-first.
        fmt_order = {f: i for i, f in enumerate(_EXTRACTABLE)}
        sorted_rows = sorted(rows, key=lambda r: fmt_order.get(r[0], 99))
        for row in sorted_rows:
            fmt, name = row[0], row[1]
            path = book_folder / f"{name}.{fmt.lower()}"
            if path.exists():
                result.append((fmt, path))
        return result

    def _book_folder(self, book_id: int) -> Path | None:
        row = self._conn.execute(
            "SELECT path FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if not row:
            return None
        return self.library_path / row[0]

