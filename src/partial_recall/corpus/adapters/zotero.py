"""ZoteroAdapter — reads from Zotero's SQLite database.

v0.0.1 scope: PDFs + abstracts only. Notes + annotations deferred to v0.1.0.

Opens zotero.sqlite in read-only mode (mode=ro&immutable=1) so it can run
concurrently with Zotero itself. Falls back to zotero.sqlite.bak if the
main DB is locked.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from partial_recall.corpus.types import Item, ItemKind, Source
from partial_recall.errors import CorpusUnavailableError
from partial_recall.extract.pdf import PdfExtractionError, extract_pdf_text


class ZoteroAdapter:
    """Read-only corpus adapter for Zotero's SQLite library."""

    name = "zotero"
    version = "1"
    capabilities = frozenset({ItemKind.TEXT, ItemKind.METADATA})

    def __init__(self, *, sqlite_path: Path, storage_path: Path):
        self.sqlite_path = Path(sqlite_path)
        self.storage_path = Path(storage_path)
        if not self.sqlite_path.exists():
            raise CorpusUnavailableError(f"Zotero DB not found: {self.sqlite_path}")
        self._conn = self._open_readonly(self.sqlite_path)

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _open_readonly(path: Path) -> sqlite3.Connection:
        uri = f"file:{path}?mode=ro&immutable=1"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=2)
            conn.row_factory = sqlite3.Row
            conn.execute("SELECT 1 FROM items LIMIT 1").fetchone()  # lock-test
            return conn
        except sqlite3.OperationalError as e:
            # Try .bak fallback
            bak = Path(str(path) + ".bak")
            if bak.exists():
                bak_uri = f"file:{bak}?mode=ro&immutable=1"
                conn = sqlite3.connect(bak_uri, uri=True, timeout=2)
                conn.row_factory = sqlite3.Row
                return conn
            raise CorpusUnavailableError(
                f"cannot open Zotero DB {path} (locked? not a Zotero DB? {e})"
            ) from e

    def list_items(self, since: datetime | None = None) -> Iterator[Item]:
        """Enumerate top-level items (not attachments, not deleted)."""
        sql = """
            SELECT i.itemID, i.key, it.typeName
            FROM items i
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND it.typeName NOT IN ('attachment', 'note')
        """
        rows = self._conn.execute(sql).fetchall()
        for row in rows:
            item_id = row["itemID"]
            item_key = row["key"]
            item_type = row["typeName"]
            fields = self._fetch_item_fields(item_id)
            creators = self._fetch_item_creators(item_id)
            title = fields.get("title")
            date = fields.get("date")
            abstract = fields.get("abstractNote")
            metadata_hash = self._compute_metadata_hash(title, date, creators, abstract)
            yield Item(
                item_key=item_key,
                corpus="zotero",
                item_type=item_type,
                title=title,
                date=date,
                creators=creators,
                abstract=abstract,
                metadata_hash=metadata_hash,
            )

    def get_sources(self, item: Item) -> Iterator[Source]:
        """Yield abstract source (if present) + one pdf source per PDF attachment."""
        row = self._conn.execute(
            "SELECT itemID FROM items WHERE key = ?", (item.item_key,)
        ).fetchone()
        if row is None:
            return
        item_id = row["itemID"]
        if item.abstract:
            yield Source(source_type="abstract", source_ref=None, kind=ItemKind.METADATA)
        att_rows = self._conn.execute(
            """
            SELECT a.itemID, a.path, child.key as att_key
            FROM itemAttachments a
            JOIN items child ON child.itemID = a.itemID
            WHERE a.parentItemID = ? AND a.contentType = 'application/pdf'
            """,
            (item_id,),
        ).fetchall()
        for att in att_rows:
            yield Source(
                source_type="pdf",
                source_ref=f"pdf:{att['att_key']}",
                kind=ItemKind.TEXT,
            )

    def get_text(self, item: Item, source: Source) -> str | None:
        if source.source_type == "abstract":
            return item.abstract
        if source.source_type == "pdf":
            pdf_path = self._resolve_pdf_path(source)
            if pdf_path is None or not pdf_path.exists():
                return None
            try:
                return extract_pdf_text(pdf_path)
            except PdfExtractionError:
                return None
        return None

    def get_image(self, item: Item, source: Source) -> bytes | None:
        return None  # v0.3.0+

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _fetch_item_fields(self, item_id: int) -> dict[str, str]:
        rows = self._conn.execute(
            """
            SELECT f.fieldName, v.value
            FROM itemData d
            JOIN fields f ON f.fieldID = d.fieldID
            JOIN itemDataValues v ON v.valueID = d.valueID
            WHERE d.itemID = ?
            """,
            (item_id,),
        ).fetchall()
        return {row["fieldName"]: row["value"] for row in rows}

    def _fetch_item_creators(self, item_id: int) -> list[dict[str, str]]:
        rows = self._conn.execute(
            """
            SELECT c.firstName, c.lastName
            FROM itemCreators ic
            JOIN creators c ON c.creatorID = ic.creatorID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """,
            (item_id,),
        ).fetchall()
        out: list[dict[str, str]] = []
        for r in rows:
            out.append({"first": r["firstName"] or "", "last": r["lastName"] or ""})
        return out

    @staticmethod
    def _compute_metadata_hash(
        title: str | None,
        date: str | None,
        creators: list[dict[str, str]],
        abstract: str | None,
    ) -> str:
        h = hashlib.sha256()
        h.update((title or "").encode("utf-8"))
        h.update(b"\x00")
        h.update((date or "").encode("utf-8"))
        h.update(b"\x00")
        h.update(json.dumps(creators, sort_keys=True).encode("utf-8"))
        h.update(b"\x00")
        h.update((abstract or "").encode("utf-8"))
        return h.hexdigest()

    def _resolve_pdf_path(self, source: Source) -> Path | None:
        """Resolve a PDF source_ref like 'pdf:<key>' to a filesystem path.

        Zotero stores attachments at storage/<KEY>/<filename>. We list the
        directory and return the first .pdf file.
        """
        if not source.source_ref or not source.source_ref.startswith("pdf:"):
            return None
        key = source.source_ref[len("pdf:"):]
        att_dir = self.storage_path / key
        if not att_dir.exists():
            return None
        for f in att_dir.iterdir():
            if f.suffix.lower() == ".pdf":
                return f
        return None
