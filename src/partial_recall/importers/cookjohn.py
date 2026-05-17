"""CookjohnImporter — one-shot migration from cookjohn/zotero-mcp vectors.

Reads cookjohn's vectors.sqlite (vectors_f32 + embeddings tables; Gemini
embedding-001 3072-dim float32 vectors), normalizes + int8-quantizes,
writes into partial-recall's schema as a new embedding_run.

NOT a runtime dependency on cookjohn — this is a one-shot migration the
user invokes via `partial-recall import cookjohn --source PATH`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from partial_recall.embedding.quantize import pack_int8, quantize_to_int8
from partial_recall.errors import CorpusUnavailableError
from partial_recall.store.vector_store import VectorStore

_COOKJOHN_DIM = 3072
_COOKJOHN_BLOB_LEN = _COOKJOHN_DIM * 4  # float32 = 4 bytes/dim


@dataclass(frozen=True)
class ImportResult:
    run_id: int
    item_count: int
    chunk_count: int
    vector_count: int


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _open_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return conn
    except sqlite3.OperationalError as e:
        raise CorpusUnavailableError(f"cannot open {path}: {e}") from e


def _fetch_zotero_item_metadata(
    zotero_conn: sqlite3.Connection,
    item_key: str,
) -> dict[str, Any]:
    """Fetch title/date/creators/abstract/type for a Zotero item_key.

    Returns a dict; missing fields → None / [].
    """
    row = zotero_conn.execute(
        """SELECT i.itemID, it.typeName
           FROM items i JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
           WHERE i.key = ?""",
        (item_key,),
    ).fetchone()
    if row is None:
        return {
            "item_type": "unknown",
            "title": None,
            "date": None,
            "creators": [],
            "abstract": None,
        }
    item_id = row["itemID"]
    item_type = row["typeName"]

    fields: dict[str, str] = {}
    for fr in zotero_conn.execute(
        """SELECT f.fieldName, v.value
           FROM itemData d
           JOIN fields f ON f.fieldID = d.fieldID
           JOIN itemDataValues v ON v.valueID = d.valueID
           WHERE d.itemID = ?""",
        (item_id,),
    ).fetchall():
        fields[fr["fieldName"]] = fr["value"]

    creators: list[dict[str, str]] = []
    for cr in zotero_conn.execute(
        """SELECT c.firstName, c.lastName
           FROM itemCreators ic
           JOIN creators c ON c.creatorID = ic.creatorID
           WHERE ic.itemID = ?
           ORDER BY ic.orderIndex""",
        (item_id,),
    ).fetchall():
        creators.append({"first": cr["firstName"] or "", "last": cr["lastName"] or ""})

    return {
        "item_type": item_type,
        "title": fields.get("title"),
        "date": fields.get("date"),
        "creators": creators,
        "abstract": fields.get("abstractNote"),
    }


def _metadata_hash(
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


def _text_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def import_cookjohn(
    *,
    cookjohn_path: Path,
    zotero_path: Path | None,
    store: VectorStore,
    activate: bool = True,
    batch_size: int = 1000,
    progress_callback: Callable[[int, int], None] | None = None,
) -> ImportResult:
    """Import cookjohn vectors into partial-recall's vector store.

    Args:
        cookjohn_path: path to cookjohn's zotero-mcp-vectors.sqlite
        zotero_path: path to Zotero's main zotero.sqlite (for item metadata
            lookup); None = skip metadata enrichment.
        store: open VectorStore to write into.
        activate: if True, mark the new embedding run active on completion.
        batch_size: cookjohn rows fetched per SQL batch.
        progress_callback: optional callback(processed, total) for UI progress.
    """
    if not cookjohn_path.exists():
        raise CorpusUnavailableError(f"cookjohn DB not found: {cookjohn_path}")
    cookjohn_conn = _open_readonly(cookjohn_path)

    zotero_conn: sqlite3.Connection | None = None
    if zotero_path is not None and zotero_path.exists():
        zotero_conn = _open_readonly(zotero_path)

    total_row = cookjohn_conn.execute(
        "SELECT COUNT(*) AS n FROM vectors_f32"
    ).fetchone()
    total = int(total_row["n"])

    started_at = _now_iso()
    run_id = store.create_run(
        provider="cookjohn-imported",
        model_name="gemini-embedding-001",
        model_version=None,
        dimensions=_COOKJOHN_DIM,
        quantization="int8",
        normalized=True,
        distance_metric="cosine",
        chunker_name="cookjohn-original",
        chunker_version="v1",
        started_at=started_at,
        notes=f"Imported from {cookjohn_path}",
    )

    items_seen: set[str] = set()
    item_count = 0
    chunk_count = 0
    vector_count = 0
    processed = 0

    cur = cookjohn_conn.execute(
        """
        SELECT vf.id, vf.item_key, vf.chunk_id, vf.vector,
               e.chunk_text
        FROM vectors_f32 vf
        LEFT JOIN embeddings e
            ON e.item_key = vf.item_key AND e.chunk_id = vf.chunk_id
        """
    )

    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        for row in rows:
            item_key = row["item_key"]
            cookjohn_chunk_id = int(row["chunk_id"])
            vector_blob = row["vector"]
            chunk_text = row["chunk_text"] or ""

            if (
                not isinstance(vector_blob, (bytes, bytearray))
                or len(vector_blob) != _COOKJOHN_BLOB_LEN
            ):
                processed += 1
                continue

            if item_key not in items_seen:
                items_seen.add(item_key)
                item_count += 1
                if zotero_conn is not None:
                    meta = _fetch_zotero_item_metadata(zotero_conn, item_key)
                else:
                    meta = {
                        "item_type": "unknown",
                        "title": None,
                        "date": None,
                        "creators": [],
                        "abstract": None,
                    }
                store.upsert_item(
                    item_key=item_key,
                    corpus="zotero",
                    item_type=meta["item_type"],
                    title=meta["title"],
                    date=meta["date"],
                    creators_json=json.dumps(meta["creators"], ensure_ascii=False),
                    abstract=meta["abstract"],
                    metadata_hash=_metadata_hash(
                        meta["title"], meta["date"], meta["creators"], meta["abstract"]
                    ),
                    last_indexed_at=_now_iso(),
                    corpus_ref="cookjohn-imported",
                )

            v_f32 = np.frombuffer(vector_blob, dtype=np.float32)
            norm = float(np.linalg.norm(v_f32))
            if norm > 0:
                v_f32 = v_f32 / norm
            q_int8 = quantize_to_int8(v_f32)
            packed = pack_int8(q_int8)
            preview = chunk_text[:400] if chunk_text else None
            th = _text_hash(chunk_text or f"cookjohn:{item_key}:{cookjohn_chunk_id}")

            source_ref = f"cookjohn:{cookjohn_chunk_id}"
            if not store.chunk_exists(
                item_key=item_key,
                corpus="zotero",
                source_type="pdf",
                source_ref=source_ref,
                chunk_index=cookjohn_chunk_id,
                chunker_version="cookjohn-original",
                text_hash=th,
            ):
                chunk_db_id = store.insert_chunk(
                    item_key=item_key,
                    corpus="zotero",
                    source_type="pdf",
                    source_ref=source_ref,
                    chunk_index=cookjohn_chunk_id,
                    char_offset_start=None,
                    char_offset_end=None,
                    text_hash=th,
                    text_preview=preview,
                    chunker_version="cookjohn-original",
                    detected_locale=None,
                    indexed_at=_now_iso(),
                )
                chunk_count += 1
            else:
                r = store._conn.execute(
                    """SELECT chunk_id FROM chunks
                       WHERE owner='local' AND corpus='zotero' AND item_key=?
                         AND source_type='pdf' AND source_ref=?
                         AND chunk_index=? AND chunker_version='cookjohn-original'
                       LIMIT 1""",
                    (item_key, source_ref, cookjohn_chunk_id),
                ).fetchone()
                if r is None:
                    processed += 1
                    continue
                chunk_db_id = int(r["chunk_id"])

            store.insert_vector(
                chunk_id=chunk_db_id,
                run_id=run_id,
                vector=packed,
                norm=None,
                indexed_at=_now_iso(),
            )
            vector_count += 1
            processed += 1
            if progress_callback is not None and processed % 100 == 0:
                progress_callback(processed, total)

    if progress_callback is not None:
        progress_callback(processed, total)

    cookjohn_conn.close()
    if zotero_conn is not None:
        zotero_conn.close()

    completed_at = _now_iso()
    store.complete_run(
        run_id=run_id,
        completed_at=completed_at,
        item_count=item_count,
        chunk_count=chunk_count,
    )
    if activate:
        store.activate_run(run_id)

    return ImportResult(
        run_id=run_id,
        item_count=item_count,
        chunk_count=chunk_count,
        vector_count=vector_count,
    )
