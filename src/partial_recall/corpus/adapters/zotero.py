"""ZoteroAdapter — reads from Zotero's SQLite database.

Sources yielded per parent item, in order: abstract (if present), one
`pdf` source per PDF attachment, one `note` source per child note,
one `annotation` source per textual annotation on each PDF attachment.

Opens zotero.sqlite in read-only mode (mode=ro&immutable=1) so it can run
concurrently with Zotero itself. Falls back to zotero.sqlite.bak if the
main DB is locked.

Annotation type filter: Zotero annotation `type` is an integer —
1=highlight, 2=note, 3=image, 4=ink, 5=underline. We index types 1, 2, 5
(text-bearing) and skip 3, 4 (no text; multimodal handling is v0.4.0).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from partial_recall.corpus.types import Item, ItemKind, Source
from partial_recall.errors import CorpusUnavailableError
from partial_recall.extract.docx import extract_docx_text
from partial_recall.extract.epub import extract_epub_text
from partial_recall.extract.pdf import PdfExtractionError, extract_pdf_text

# Zotero annotation types we treat as text. See module docstring.
_TEXTUAL_ANNOTATION_TYPES = (1, 2, 5)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# After stripping inline tags around punctuation we can get "word ." —
# collapse whitespace before terminal/clause punctuation.
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?)\]])")


def _strip_html(s: str | None) -> str:
    """Naive HTML → text for Zotero notes.

    Zotero stores notes as fairly simple HTML produced by its own editor.
    A full parser is overkill; strip tags, decode entities, collapse
    whitespace, and fix space-before-punctuation artefacts from inline
    tag removal.
    """
    if not s:
        return ""
    text = _TAG_RE.sub(" ", s)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    return text.strip()


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
        # Feature flags: some test fixtures (and possibly trimmed Zotero
        # forks) omit these tables. Treat their absence as "no notes /
        # annotations to index" rather than as a hard error.
        self._has_notes = self._table_exists("itemNotes")
        self._has_annotations = self._table_exists("itemAnnotations")

    def _table_exists(self, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None

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

    # ------------------------------------------------------------------
    # Collections (v0.2.4) — Zotero's user-defined folders / library
    # sub-divisions. The CLI calls these to populate the collections
    # + item_collections tables before indexing.
    # ------------------------------------------------------------------

    def list_zotero_collections(self) -> Iterator[dict]:
        """Yield each Zotero collection with its key, name, and the
        key of its parent (if nested), one row per collection.

        Excludes deleted collections."""
        if not self._table_exists("collections"):
            return
        sql = """
            SELECT
                c.key            AS collection_key,
                c.collectionName AS name,
                parent.key       AS parent_key
            FROM collections c
            LEFT JOIN collections parent
                ON parent.collectionID = c.parentCollectionID
            WHERE c.collectionID NOT IN (SELECT collectionID FROM deletedCollections)
        """
        for row in self._conn.execute(sql).fetchall():
            yield {
                "collection_key": row["collection_key"],
                "name": row["name"],
                "parent_key": row["parent_key"],
            }

    def list_collection_memberships(self) -> Iterator[dict]:
        """Yield (item_key, collection_key) pairs for every
        item-in-collection edge in the Zotero library. Skips
        attachments / notes / deleted items."""
        if not self._table_exists("collectionItems"):
            return
        sql = """
            SELECT i.key AS item_key, c.key AS collection_key
            FROM collectionItems ci
            JOIN items i        ON i.itemID = ci.itemID
            JOIN collections c  ON c.collectionID = ci.collectionID
            JOIN itemTypes it   ON it.itemTypeID = i.itemTypeID
            WHERE it.typeName NOT IN ('attachment', 'note')
              AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND c.collectionID NOT IN (SELECT collectionID FROM deletedCollections)
        """
        for row in self._conn.execute(sql).fetchall():
            yield {
                "item_key": row["item_key"],
                "collection_key": row["collection_key"],
            }

    def count_items(self, since: datetime | None = None) -> int | None:
        """Cheap COUNT(*) over the same filter list_items() uses."""
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM items i
            JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
            WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND it.typeName NOT IN ('attachment', 'note')
            """,
        ).fetchone()
        return int(row["n"]) if row is not None else None

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
            # v0.2.4: library-location richness. These tell a reader
            # where the physical / catalogued copy of an item lives.
            archive = fields.get("archive")
            archive_location = fields.get("archiveLocation")
            call_number = fields.get("callNumber")
            library_catalog = fields.get("libraryCatalog")
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
                archive=archive,
                archive_location=archive_location,
                call_number=call_number,
                library_catalog=library_catalog,
            )

    def get_sources(self, item: Item) -> Iterator[Source]:
        """Yield all indexable sources attached to a parent item.

        Order: abstract → pdf(s) → note(s) → annotation(s). Deleted
        children are excluded. Annotations on deleted attachments are
        also excluded (the SQL only joins non-deleted attachments).
        """
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
            WHERE a.parentItemID = ?
              AND a.contentType IN (
                  'application/pdf',
                  'application/epub+zip',
                  'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
              )
              AND child.itemID NOT IN (SELECT itemID FROM deletedItems)
            """,
            (item_id,),
        ).fetchall()
        for att in att_rows:
            # Determine source_type from content type or path
            # But we don't have contentType in the SELECT output.
            # Let's infer from extension or att_key
            source_type = "pdf"
            if att["path"]:
                if att["path"].lower().endswith(".epub"):
                    source_type = "epub"
                elif att["path"].lower().endswith(".docx"):
                    source_type = "docx"

            yield Source(
                source_type=source_type,
                source_ref=f"{source_type}:{att['att_key']}",
                kind=ItemKind.TEXT,
            )
        note_rows = (
            self._conn.execute(
                """
            SELECT child.key AS note_key
            FROM itemNotes n
            JOIN items child ON child.itemID = n.itemID
            WHERE n.parentItemID = ?
              AND child.itemID NOT IN (SELECT itemID FROM deletedItems)
            """,
                (item_id,),
            ).fetchall()
            if self._has_notes
            else []
        )
        for nr in note_rows:
            yield Source(
                source_type="note",
                source_ref=f"note:{nr['note_key']}",
                kind=ItemKind.TEXT,
            )
        # Annotations live on the attachment (the PDF), not on the parent
        # bibliographic item. Two-hop join: parent → attachment → annotation.
        # Use a placeholder-list for the type filter so the IN-clause stays
        # parameterised.
        type_placeholders = ",".join("?" * len(_TEXTUAL_ANNOTATION_TYPES))
        ann_rows = (
            self._conn.execute(
                f"""
            SELECT child.key AS ann_key
            FROM itemAnnotations ann
            JOIN itemAttachments att ON att.itemID = ann.parentItemID
            JOIN items child ON child.itemID = ann.itemID
            WHERE att.parentItemID = ?
              AND att.contentType = 'application/pdf'
              AND att.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND child.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND ann.type IN ({type_placeholders})
            ORDER BY ann.sortIndex
            """,
                (item_id, *_TEXTUAL_ANNOTATION_TYPES),
            ).fetchall()
            if self._has_annotations
            else []
        )
        for ar in ann_rows:
            yield Source(
                source_type="annotation",
                source_ref=f"annotation:{ar['ann_key']}",
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
        if source.source_type == "epub":
            epub_path = self._resolve_pdf_path(source) # _resolve_pdf_path works for any attachment key
            if epub_path is None or not epub_path.exists():
                return None
            return extract_epub_text(epub_path)
        if source.source_type == "docx":
            docx_path = self._resolve_pdf_path(source)
            if docx_path is None or not docx_path.exists():
                return None
            return extract_docx_text(docx_path)
        if source.source_type == "note":
            return self._get_note_text(source)
        if source.source_type == "annotation":
            return self._get_annotation_text(source)
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

    def _get_note_text(self, source: Source) -> str | None:
        if not self._has_notes:
            return None
        if not source.source_ref or not source.source_ref.startswith("note:"):
            return None
        key = source.source_ref[len("note:") :]
        row = self._conn.execute(
            """
            SELECT n.note, n.title
            FROM itemNotes n
            JOIN items i ON i.itemID = n.itemID
            WHERE i.key = ?
            """,
            (key,),
        ).fetchone()
        if row is None:
            return None
        body = _strip_html(row["note"])
        title = (row["title"] or "").strip()
        if title and not body.startswith(title):
            return f"{title}\n\n{body}" if body else title
        return body or None

    def _get_annotation_text(self, source: Source) -> str | None:
        if not self._has_annotations:
            return None
        if not source.source_ref or not source.source_ref.startswith("annotation:"):
            return None
        key = source.source_ref[len("annotation:") :]
        row = self._conn.execute(
            """
            SELECT ann.text, ann.comment, ann.pageLabel
            FROM itemAnnotations ann
            JOIN items i ON i.itemID = ann.itemID
            WHERE i.key = ?
            """,
            (key,),
        ).fetchone()
        if row is None:
            return None
        text = (row["text"] or "").strip()
        comment = (row["comment"] or "").strip()
        page = (row["pageLabel"] or "").strip()
        parts: list[str] = []
        if text:
            parts.append(text)
        if comment:
            parts.append(f"— {comment}")
        if page:
            parts.append(f"(p. {page})")
        joined = " ".join(parts).strip()
        return joined or None

    def _resolve_pdf_path(self, source: Source) -> Path | None:
        """Resolve a PDF source_ref like 'pdf:<key>' to a filesystem path.

        Zotero stores attachments at storage/<KEY>/<filename>. We list the
        directory and return the first .pdf file.
        """
        if not source.source_ref or not source.source_ref.startswith("pdf:"):
            return None
        key = source.source_ref[len("pdf:") :]
        att_dir = self.storage_path / key
        if not att_dir.exists():
            return None
        for f in att_dir.iterdir():
            if f.suffix.lower() == ".pdf":
                return f
        return None
