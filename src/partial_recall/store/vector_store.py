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
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO items (
                item_key, corpus, item_type, title, date, creators_json,
                abstract, metadata_hash, last_indexed_at, corpus_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (owner, corpus, item_key) DO UPDATE SET
                item_type = excluded.item_type,
                title = excluded.title,
                date = excluded.date,
                creators_json = excluded.creators_json,
                abstract = excluded.abstract,
                metadata_hash = excluded.metadata_hash,
                last_indexed_at = excluded.last_indexed_at,
                corpus_ref = excluded.corpus_ref
            """,
            (
                item_key, corpus, item_type, title, date, creators_json,
                abstract, metadata_hash, last_indexed_at, corpus_ref,
            ),
        )

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
