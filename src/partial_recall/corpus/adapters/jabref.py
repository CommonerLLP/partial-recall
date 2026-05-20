"""JabRefAdapter — index a JabRef / BibTeX bibliography (v0.3.0).

JabRef is a free, open-source reference manager used widely in academia.
It stores its library as a plain-text .bib (BibTeX) file. This adapter
reads that file and makes every reference entry (article, book, thesis,
etc.) available for semantic indexing.

What gets indexed per entry:
  - Title, authors, abstract, keywords → Item metadata
  - Abstract text → primary indexable source
  - Linked PDF (via the `file` field JabRef writes) → extracted and indexed
    if the file exists on disk. JabRef stores paths like
    `:path/to/paper.pdf:PDF` — we parse and resolve them.

No JabRef installation required — the adapter reads the .bib file
directly. Works with any BibTeX-format bibliography (Zotero exported
.bib, Mendeley exported .bib, hand-written .bib, etc.).

Requires the `bibtexparser` package (optional dep):
    pipx inject partial-recall bibtexparser
    OR: pip install 'partial-recall[jabref]'
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import structlog

from partial_recall.corpus.adapters._shared import stable_item_key
from partial_recall.corpus.types import Item, ItemKind, Source
from partial_recall.errors import CorpusUnavailableError, PartialRecallError

log = structlog.get_logger(__name__)

# JabRef writes file links as `:description:path:type` or `:path:type`.
# We extract the path component and resolve PDFs.
# The path alternation handles Windows absolute paths (C:\...) whose drive-letter
# colon would otherwise split into a spurious extra field.
_FILE_FIELD_RE = re.compile(r":([^:]*):([A-Za-z]:[^:]+|[^:]+):([^:]*)")


class JabRefAdapterError(PartialRecallError):
    """JabRefAdapter-specific failure."""


def _require_bibtexparser() -> None:
    try:
        import bibtexparser  # noqa: F401  # type: ignore[import-not-found]
    except ImportError as e:
        raise JabRefAdapterError(
            "The `bibtexparser` package is required to index BibTeX files. "
            "Install it with `pipx inject partial-recall bibtexparser` or "
            "`pip install bibtexparser`."
        ) from e


def _parse_authors(author_field: str) -> list[dict[str, str]]:
    """Split a BibTeX `author` field into a list of creator dicts.

    BibTeX separates authors with ' and '. Each name may be 'Last, First'
    or 'First Last'.
    """
    if not author_field:
        return []
    creators = []
    for raw in re.split(r"\s+and\s+", author_field, flags=re.IGNORECASE):
        name = raw.strip()
        if "," in name:
            parts = name.split(",", 1)
            creators.append({"last": parts[0].strip(), "first": parts[1].strip()})
        else:
            parts = name.rsplit(" ", 1)
            if len(parts) == 2:
                creators.append({"first": parts[0].strip(), "last": parts[1].strip()})
            else:
                creators.append({"last": name, "first": ""})
    return creators


def _resolve_file_links(file_field: str, bib_dir: Path) -> list[Path]:
    """Parse JabRef's `file` field and return resolved PDF paths that exist.

    JabRef writes:
        file = {:relative/path.pdf:PDF}
        file = {Description:absolute/path.pdf:PDF;:another.pdf:PDF}
    """
    if not file_field:
        return []
    found: list[Path] = []
    for m in _FILE_FIELD_RE.finditer(file_field):
        raw_path = m.group(2).strip()
        if not raw_path:
            continue
        p = Path(raw_path)
        if not p.is_absolute():
            p = bib_dir / p
        p = p.resolve()
        if p.exists() and p.suffix.lower() == ".pdf":
            found.append(p)
    return found


class JabRefAdapter:
    """Read-only corpus adapter for a JabRef / BibTeX .bib file."""

    name = "jabref"
    version = "1"
    capabilities = frozenset({ItemKind.TEXT, ItemKind.METADATA})

    def __init__(self, *, bib_path: Path) -> None:
        _require_bibtexparser()
        self.bib_path = Path(bib_path).resolve()
        if not self.bib_path.exists():
            raise CorpusUnavailableError(
                f"BibTeX file not found: {self.bib_path}"
            )
        if not self.bib_path.is_file():
            raise CorpusUnavailableError(
                f"BibTeX path is not a file: {self.bib_path}"
            )
        self._bib_dir = self.bib_path.parent
        self._library = self._load()
        self._entries_by_key: dict[str, dict] = {
            e["ID"]: e for e in self._library.entries if e.get("ID")
        }

    def _load(self):  # type: ignore[return]
        import bibtexparser  # type: ignore[import-not-found]
        with self.bib_path.open(encoding="utf-8", errors="replace") as f:
            return bibtexparser.load(f)

    def close(self) -> None:
        return None

    # ------------------------------------------------------------------
    # CorpusAdapter Protocol
    # ------------------------------------------------------------------

    def count_items(self, since: datetime | None = None) -> int | None:
        return len(self._library.entries)

    def list_items(self, since: datetime | None = None) -> Iterator[Item]:
        for entry in self._library.entries:
            key = entry.get("ID", "")
            if not key:
                continue
            title = entry.get("title", "").strip("{}")
            abstract = entry.get("abstract", "").strip("{}")
            year = entry.get("year", "")
            author_field = entry.get("author", "")
            creators = _parse_authors(author_field)
            item_key = stable_item_key(Path(key + ".bib")) if key else hashlib.sha256(
                str(entry).encode("utf-8")
            ).hexdigest()[:16]
            # Use the BibTeX key as a more readable stable identifier
            h = hashlib.sha256(f"{self.bib_path}:{key}".encode()).hexdigest()[:12]
            stem = "".join(c if c.isalnum() else "_" for c in key.lower())[:30]
            item_key = f"{h}-{stem}" if stem else h

            metadata_hash = hashlib.sha256(
                str(entry).encode("utf-8")
            ).hexdigest()
            yield Item(
                item_key=item_key,
                corpus="jabref",
                item_type=entry.get("ENTRYTYPE", "misc"),
                title=title or key,
                date=year or None,
                creators=creators,
                abstract=abstract or None,
                metadata_hash=metadata_hash,
                corpus_ref=key,
            )

    def get_sources(self, item: Item) -> Iterator[Source]:
        if not item.corpus_ref:
            return
        entry = self._entry_by_key(item.corpus_ref)
        if entry is None:
            return
        # Abstract as a text source (always first — always available)
        if item.abstract:
            yield Source(
                source_type="abstract",
                source_ref=item.corpus_ref,
                kind=ItemKind.TEXT,
            )
        # Linked PDFs
        file_field = entry.get("file", "")
        for pdf_path in _resolve_file_links(file_field, self._bib_dir):
            yield Source(
                source_type="pdf",
                source_ref=str(pdf_path),
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
                log.warning("jabref.adapter.pdf_failed", path=source.source_ref, error=str(e))
                return None
        return None

    def get_image(self, item: Item, source: Source) -> bytes | None:
        return None  # v0.4.0+

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _entry_by_key(self, key: str) -> dict | None:
        return self._entries_by_key.get(key)
