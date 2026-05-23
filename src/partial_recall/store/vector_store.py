"""High-level vector store wrapping the v0.0.1 SQLite schema."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from partial_recall.store.connection import connect


@dataclass(frozen=True)
class RunInfo:
    run_id: int
    provider: str
    model_name: str
    dimensions: int
    quantization: str
    normalized: bool
    distance_metric: str
    chunker_version: str
    is_active: bool


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    score: float
    item_key: str
    corpus: str
    source_type: str
    source_ref: str | None
    text_preview: str | None
    chunk_index: int
    char_offset_start: int | None
    char_offset_end: int | None
    detected_locale: str | None


class VectorStore:
    """SQLite-backed vector store. Holds one connection for the lifetime of the object."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn = connect(self.db_path)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    def create_run(
        self,
        *,
        provider: str,
        model_name: str,
        model_version: str | None,
        dimensions: int,
        quantization: str,
        normalized: bool,
        distance_metric: str,
        chunker_name: str,
        chunker_version: str,
        started_at: str,
        notes: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO embedding_runs (
                provider, model_name, model_version, dimensions, quantization,
                normalized, distance_metric, chunker_name, chunker_version,
                started_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider, model_name, model_version, dimensions, quantization,
                int(normalized), distance_metric, chunker_name, chunker_version,
                started_at, notes,
            ),
        )
        assert cur.lastrowid is not None  # AUTOINCREMENT INSERT always sets it
        return int(cur.lastrowid)

    def complete_run(
        self,
        run_id: int,
        completed_at: str,
        item_count: int,
        chunk_count: int,
    ) -> None:
        self._conn.execute(
            """
            UPDATE embedding_runs
            SET completed_at = ?, item_count = ?, chunk_count = ?
            WHERE run_id = ?
            """,
            (completed_at, item_count, chunk_count, run_id),
        )

    def activate_run(self, run_id: int) -> None:
        self._conn.execute("UPDATE embedding_runs SET is_active = 0")
        self._conn.execute(
            "UPDATE embedding_runs SET is_active = 1 WHERE run_id = ?", (run_id,)
        )

    def get_run(self, run_id: int) -> RunInfo | None:
        row = self._conn.execute(
            """
            SELECT run_id, provider, model_name, dimensions, quantization,
                   normalized, distance_metric, chunker_version, is_active
            FROM embedding_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunInfo(
            run_id=row["run_id"], provider=row["provider"],
            model_name=row["model_name"], dimensions=row["dimensions"],
            quantization=row["quantization"], normalized=bool(row["normalized"]),
            distance_metric=row["distance_metric"],
            chunker_version=row["chunker_version"], is_active=bool(row["is_active"]),
        )

    def update_run_counts(
        self,
        run_id: int,
        item_count: int,
        chunk_count: int,
    ) -> None:
        self._conn.execute(
            "UPDATE embedding_runs SET item_count = ?, chunk_count = ? WHERE run_id = ?",
            (item_count, chunk_count, run_id),
        )

    # ------------------------------------------------------------------
    # Indexing progress (v0.2.2 B4)
    # ------------------------------------------------------------------
    def set_indexing_progress(
        self,
        *,
        run_id: int,
        last_processed_key: str | None,
    ) -> None:
        """Record per-run progress after a successful batch flush.

        Called by the pipeline after each batch is fully written to
        vectors. `last_processed_key` is the item_key of the last item
        whose chunks were all flushed. On resume, items with
        item_key <= last_processed_key (in deterministic sort order)
        can be fast-skipped without re-walking their sources.
        """
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self._conn.execute(
            """
            INSERT INTO indexing_progress (run_id, last_processed_key, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (run_id) DO UPDATE SET
                last_processed_key = excluded.last_processed_key,
                updated_at = excluded.updated_at
            """,
            (run_id, last_processed_key, now),
        )

    def get_indexing_progress(self, run_id: int) -> str | None:
        """Return last_processed_key for a run, or None if no progress recorded."""
        row = self._conn.execute(
            "SELECT last_processed_key FROM indexing_progress WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return row["last_processed_key"] if row is not None else None

    def clear_indexing_progress(self, run_id: int) -> None:
        """Drop the progress row for a run (e.g. when a run completes cleanly)."""
        self._conn.execute(
            "DELETE FROM indexing_progress WHERE run_id = ?", (run_id,)
        )

    def recompute_run_counts(self, run_id: int) -> tuple[int, int]:
        """Recompute item_count and chunk_count for a run from its vectors.

        Used after extend-run top-up. Returns (item_count, chunk_count).
        """
        row = self._conn.execute(
            """
            SELECT
                COUNT(DISTINCT c.item_key) AS items,
                COUNT(*) AS chunks
            FROM vectors v
            JOIN chunks c ON c.chunk_id = v.chunk_id
            WHERE v.run_id = ?
            """,
            (run_id,),
        ).fetchone()
        items = int(row["items"] or 0)
        chunks = int(row["chunks"] or 0)
        self._conn.execute(
            "UPDATE embedding_runs SET item_count = ?, chunk_count = ? WHERE run_id = ?",
            (items, chunks, run_id),
        )
        return (items, chunks)

    def get_active_run(self) -> RunInfo | None:
        row = self._conn.execute(
            """
            SELECT run_id, provider, model_name, dimensions, quantization,
                   normalized, distance_metric, chunker_version, is_active
            FROM embedding_runs
            WHERE is_active = 1
            ORDER BY run_id DESC
            LIMIT 1
            """,
        ).fetchone()
        if row is None:
            return None
        return RunInfo(
            run_id=row["run_id"], provider=row["provider"],
            model_name=row["model_name"], dimensions=row["dimensions"],
            quantization=row["quantization"], normalized=bool(row["normalized"]),
            distance_metric=row["distance_metric"],
            chunker_version=row["chunker_version"], is_active=bool(row["is_active"]),
        )

    def list_runs(self) -> list[RunInfo]:
        rows = self._conn.execute(
            """
            SELECT run_id, provider, model_name, dimensions, quantization,
                   normalized, distance_metric, chunker_version, is_active
            FROM embedding_runs ORDER BY run_id
            """,
        ).fetchall()
        return [
            RunInfo(
                run_id=r["run_id"], provider=r["provider"],
                model_name=r["model_name"], dimensions=r["dimensions"],
                quantization=r["quantization"], normalized=bool(r["normalized"]),
                distance_metric=r["distance_metric"],
                chunker_version=r["chunker_version"], is_active=bool(r["is_active"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------
    def upsert_item(
        self,
        *,
        item_key: str,
        corpus: str,
        item_type: str,
        title: str | None,
        date: str | None,
        creators_json: str,
        abstract: str | None,
        metadata_hash: str,
        last_indexed_at: str,
        corpus_ref: str | None,
        archive: str | None = None,
        archive_location: str | None = None,
        call_number: str | None = None,
        library_catalog: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO items (
                item_key, corpus, item_type, title, date, creators_json,
                abstract, metadata_hash, last_indexed_at, corpus_ref,
                archive, archive_location, call_number, library_catalog
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (owner, corpus, item_key) DO UPDATE SET
                item_type = excluded.item_type,
                title = excluded.title,
                date = excluded.date,
                creators_json = excluded.creators_json,
                abstract = excluded.abstract,
                metadata_hash = excluded.metadata_hash,
                last_indexed_at = excluded.last_indexed_at,
                corpus_ref = excluded.corpus_ref,
                archive = excluded.archive,
                archive_location = excluded.archive_location,
                call_number = excluded.call_number,
                library_catalog = excluded.library_catalog
            """,
            (
                item_key, corpus, item_type, title, date, creators_json,
                abstract, metadata_hash, last_indexed_at, corpus_ref,
                archive, archive_location, call_number, library_catalog,
            ),
        )

    # ------------------------------------------------------------------
    # Collections (Zotero "folders" within a library), v0.2.4
    # ------------------------------------------------------------------
    def upsert_collection(
        self,
        *,
        corpus: str,
        collection_key: str,
        name: str,
        parent_key: str | None,
        last_indexed_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO collections (
                corpus, collection_key, name, parent_key, last_indexed_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (owner, corpus, collection_key) DO UPDATE SET
                name = excluded.name,
                parent_key = excluded.parent_key,
                last_indexed_at = excluded.last_indexed_at
            """,
            (corpus, collection_key, name, parent_key, last_indexed_at),
        )

    def clear_collection_memberships(self, corpus: str) -> int:
        """Remove ALL item↔collection rows for `corpus`.

        Used at the top of a collection-sync pass so stale memberships
        (items removed from collections in Zotero between runs, or
        whole collections deleted) don't linger. Returns the row count
        removed. Codex P2 review on PR #13.
        """
        cur = self._conn.execute(
            "DELETE FROM item_collections WHERE owner = 'local' AND corpus = ?",
            (corpus,),
        )
        return cur.rowcount or 0

    def link_item_to_collection(
        self,
        *,
        corpus: str,
        item_key: str,
        collection_key: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO item_collections (corpus, item_key, collection_key)
            VALUES (?, ?, ?)
            ON CONFLICT (owner, corpus, item_key, collection_key) DO NOTHING
            """,
            (corpus, item_key, collection_key),
        )

    def list_collections_for_corpus(
        self, corpus: str
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT
                c.collection_key,
                c.name,
                c.parent_key,
                (SELECT COUNT(*) FROM item_collections ic
                  WHERE ic.owner = 'local'
                    AND ic.corpus = c.corpus
                    AND ic.collection_key = c.collection_key) AS item_count
            FROM collections c
            WHERE c.owner = 'local' AND c.corpus = ?
            ORDER BY c.name
            """,
            (corpus,),
        ).fetchall()
        return [
            {
                "collection_key": row["collection_key"],
                "name": row["name"],
                "parent_key": row["parent_key"],
                "item_count": int(row["item_count"]),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------
    def insert_chunk(
        self,
        *,
        item_key: str,
        corpus: str,
        source_type: str,
        source_ref: str | None,
        chunk_index: int,
        char_offset_start: int | None,
        char_offset_end: int | None,
        text_hash: str,
        text_preview: str | None,
        chunker_version: str,
        detected_locale: str | None,
        indexed_at: str,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO chunks (
                item_key, corpus, source_type, source_ref, chunk_index,
                char_offset_start, char_offset_end, text_hash, text_preview,
                chunker_version, detected_locale, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_key, corpus, source_type, source_ref, chunk_index,
                char_offset_start, char_offset_end, text_hash, text_preview,
                chunker_version, detected_locale, indexed_at,
            ),
        )
        assert cur.lastrowid is not None  # AUTOINCREMENT INSERT always sets it
        return int(cur.lastrowid)

    def find_chunk_id(
        self,
        *,
        item_key: str,
        corpus: str,
        source_type: str,
        source_ref: str | None,
        chunk_index: int,
        chunker_version: str,
        text_hash: str,
    ) -> tuple[int, str] | None:
        """Locate a chunk by its identity tuple; return (chunk_id, stored_text_hash) or None.

        Identity is the DB unique constraint: (owner, corpus, item_key,
        source_type, source_ref, chunk_index, chunker_version).  text_hash is
        content, not position — it is intentionally excluded from the WHERE
        clause so that a chunk whose source text changed is still found here.

        The caller receives the stored text_hash so it can detect content
        drift and call update_chunk_content() if needed.
        """
        row = self._conn.execute(
            """
            SELECT chunk_id, text_hash FROM chunks
            WHERE owner = 'local'
              AND corpus = ?
              AND item_key = ?
              AND source_type = ?
              AND (source_ref IS ? OR source_ref = ?)
              AND chunk_index = ?
              AND chunker_version = ?
            LIMIT 1
            """,
            (
                corpus, item_key, source_type, source_ref, source_ref,
                chunk_index, chunker_version,
            ),
        ).fetchone()
        return None if row is None else (int(row["chunk_id"]), str(row["text_hash"]))

    def update_chunk_content(
        self,
        *,
        chunk_id: int,
        text_hash: str,
        text_preview: str | None,
    ) -> None:
        """Update text_hash and text_preview for an existing chunk.

        Called when a source file's content changes between index runs.
        The chunks_fts trigger fires automatically to keep FTS in sync.
        """
        self._conn.execute(
            "UPDATE chunks SET text_hash = ?, text_preview = ? WHERE chunk_id = ?",
            (text_hash, text_preview, chunk_id),
        )

    def vector_exists(self, chunk_id: int, run_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM vectors WHERE chunk_id = ? AND run_id = ? LIMIT 1",
            (chunk_id, run_id),
        ).fetchone()
        return row is not None

    def chunk_exists(
        self,
        *,
        item_key: str,
        corpus: str,
        source_type: str,
        source_ref: str | None,
        chunk_index: int,
        chunker_version: str,
        text_hash: str,
    ) -> bool:
        row = self._conn.execute(
            """
            SELECT 1 FROM chunks
            WHERE owner = 'local'
              AND corpus = ?
              AND item_key = ?
              AND source_type = ?
              AND (source_ref IS ? OR source_ref = ?)
              AND chunk_index = ?
              AND chunker_version = ?
              AND text_hash = ?
            LIMIT 1
            """,
            (
                corpus, item_key, source_type, source_ref, source_ref,
                chunk_index, chunker_version, text_hash,
            ),
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Vectors
    # ------------------------------------------------------------------
    def insert_vector(
        self,
        *,
        chunk_id: int,
        run_id: int,
        vector: bytes,
        norm: float | None,
        indexed_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO vectors (chunk_id, run_id, vector, norm, indexed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chunk_id, run_id, vector, norm, indexed_at),
        )

    def top_k_int8(
        self,
        *,
        run_id: int,
        query_vector: bytes,
        k: int = 10,
        corpus: str | None = None,
    ) -> list[SearchHit]:
        """Brute-force top-K cosine similarity over int8-quantized vectors.

        Assumes both stored and query vectors are L2-normalized int8 (i.e.,
        cosine ≈ dot ÷ 127²).
        """
        # Lazy import: keeps VectorStore() construction light for
        # metadata-only callers that never search.
        import numpy as np

        q = np.frombuffer(query_vector, dtype=np.int8).astype(np.int32)
        q_norm_sq = float(np.dot(q, q))
        if q_norm_sq == 0.0:
            return []

        results: list[tuple[float, int]] = []

        if corpus is not None:
            cur = self._conn.execute(
                """
                SELECT v.vector_id, v.chunk_id, v.vector
                FROM vectors v
                JOIN chunks c ON c.chunk_id = v.chunk_id
                WHERE v.run_id = ?
                  AND c.corpus = ?
                """,
                (run_id, corpus),
            )
        else:
            cur = self._conn.execute(
                """
                SELECT vector_id, chunk_id, vector
                FROM vectors
                WHERE run_id = ?
                """,
                (run_id,),
            )
        while True:
            rows = cur.fetchmany(2048)
            if not rows:
                break
            for row in rows:
                v = np.frombuffer(row["vector"], dtype=np.int8).astype(np.int32)
                v_norm_sq = float(np.dot(v, v))
                if v_norm_sq == 0.0:
                    continue
                dot = float(np.dot(q, v))
                score = dot / ((q_norm_sq * v_norm_sq) ** 0.5)
                if len(results) < k:
                    results.append((score, row["chunk_id"]))
                    results.sort(reverse=True)
                elif score > results[-1][0]:
                    results.append((score, row["chunk_id"]))
                    results.sort(reverse=True)
                    results = results[:k]

        if not results:
            return []

        chunk_ids = [cid for _, cid in results]
        placeholders = ",".join("?" * len(chunk_ids))
        meta_rows = self._conn.execute(
            f"""
            SELECT chunk_id, item_key, corpus, source_type, source_ref,
                   chunk_index, char_offset_start, char_offset_end,
                   text_preview, detected_locale
            FROM chunks
            WHERE chunk_id IN ({placeholders})
            """,  # noqa: S608
            chunk_ids,
        ).fetchall()
        meta_by_id = {r["chunk_id"]: r for r in meta_rows}

        hits: list[SearchHit] = []
        for score, cid in results:
            r = meta_by_id.get(cid)
            if r is None:
                continue
            hits.append(SearchHit(
                chunk_id=cid, score=score,
                item_key=r["item_key"], corpus=r["corpus"],
                source_type=r["source_type"], source_ref=r["source_ref"],
                text_preview=r["text_preview"], chunk_index=r["chunk_index"],
                char_offset_start=r["char_offset_start"],
                char_offset_end=r["char_offset_end"],
                detected_locale=r["detected_locale"],
            ))
        return hits

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    def __enter__(self) -> VectorStore:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
