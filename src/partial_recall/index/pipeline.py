"""Indexing pipeline: walk corpus → extract → chunk → embed → store.

v0.0.1 = serial execution, no resume. Resumable indexing
(indexing_progress table) is v0.1.0.

Idempotency: chunks are deduplicated via text_hash (see VectorStore.chunk_exists).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from partial_recall.chunk.recursive_char import CHUNKER_VERSION, chunk_text
from partial_recall.corpus.protocol import CorpusAdapter
from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.store.vector_store import VectorStore

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IndexResult:
    run_id: int
    item_count: int
    chunk_count: int
    new_vector_count: int


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _text_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def run_indexing(
    *,
    adapter: CorpusAdapter,
    store: VectorStore,
    provider: EmbeddingProvider,
    batch_size: int = 32,
    activate: bool = True,
) -> IndexResult:
    """Run a full indexing pass.

    Creates a new embedding_run, walks the adapter for items, extracts text,
    chunks it, embeds new chunks, writes vectors to the store. Returns IndexResult.

    On completion (success path), marks the new run active if `activate=True`.
    """
    started_at = _now_iso()
    meta = provider.metadata
    run_id = store.create_run(
        provider=meta.provider,
        model_name=meta.model_name,
        model_version=meta.model_version,
        dimensions=meta.dimensions,
        quantization=provider.quantization.value,
        normalized=meta.normalized,
        distance_metric=meta.distance_metric.value,
        chunker_name=CHUNKER_VERSION,
        chunker_version=CHUNKER_VERSION,
        started_at=started_at,
    )
    log.info("indexing.run.start", run_id=run_id, provider=meta.provider, model=meta.model_name)

    item_count = 0
    chunk_count = 0
    new_vector_count = 0

    # Collect (chunk_id, text) pairs into batches for embedding
    pending: list[tuple[int, str]] = []

    def flush_pending() -> int:
        """Embed and store the pending batch. Returns number of vectors written."""
        nonlocal new_vector_count
        if not pending:
            return 0
        chunk_ids = [cid for cid, _ in pending]
        texts = [t for _, t in pending]
        batch = provider.embed(texts, task="search_document", batch_size=batch_size)
        if batch.vectors is None:
            log.warning("indexing.embed.no_vectors", count=len(texts))
            pending.clear()
            return 0
        for chunk_id, vec in zip(chunk_ids, batch.vectors, strict=True):
            store.insert_vector(
                chunk_id=chunk_id,
                run_id=run_id,
                vector=vec,
                norm=None,
                indexed_at=_now_iso(),
            )
            new_vector_count += 1
        written = len(pending)
        pending.clear()
        return written

    for item in adapter.list_items():
        item_count += 1
        # Upsert item metadata
        store.upsert_item(
            item_key=item.item_key,
            corpus=item.corpus,
            item_type=item.item_type,
            title=item.title,
            date=item.date,
            creators_json=json.dumps(item.creators, ensure_ascii=False),
            abstract=item.abstract,
            metadata_hash=item.metadata_hash,
            last_indexed_at=_now_iso(),
            corpus_ref=item.corpus_ref,
        )
        # For each source: extract → chunk → record
        for source in adapter.get_sources(item):
            text = adapter.get_text(item, source)
            if not text:
                continue
            chunks = chunk_text(text)
            for chunk in chunks:
                th = _text_hash(chunk.text)
                # Skip if same chunk (by hash+location) already exists for this chunker_version
                if store.chunk_exists(
                    item_key=item.item_key,
                    corpus=item.corpus,
                    source_type=source.source_type,
                    source_ref=source.source_ref,
                    chunk_index=chunk.chunk_index,
                    chunker_version=CHUNKER_VERSION,
                    text_hash=th,
                ):
                    # Chunk already in DB; we still need to embed it for THIS run
                    # Fetch its existing chunk_id
                    row = store._conn.execute(
                        """SELECT chunk_id FROM chunks
                           WHERE corpus = ? AND item_key = ? AND source_type = ?
                             AND (source_ref IS ? OR source_ref = ?)
                             AND chunk_index = ? AND chunker_version = ? AND text_hash = ?
                           LIMIT 1""",
                        (item.corpus, item.item_key, source.source_type,
                         source.source_ref, source.source_ref,
                         chunk.chunk_index, CHUNKER_VERSION, th),
                    ).fetchone()
                    if row is None:
                        continue
                    chunk_id = row["chunk_id"]
                else:
                    preview = chunk.text[:400] if len(chunk.text) > 400 else chunk.text
                    chunk_id = store.insert_chunk(
                        item_key=item.item_key,
                        corpus=item.corpus,
                        source_type=source.source_type,
                        source_ref=source.source_ref,
                        chunk_index=chunk.chunk_index,
                        char_offset_start=chunk.char_offset_start,
                        char_offset_end=chunk.char_offset_end,
                        text_hash=th,
                        text_preview=preview,
                        chunker_version=CHUNKER_VERSION,
                        detected_locale=None,  # locale detection deferred
                        indexed_at=_now_iso(),
                    )
                    chunk_count += 1
                pending.append((chunk_id, chunk.text))
                if len(pending) >= batch_size:
                    flush_pending()

    # Flush final batch
    flush_pending()

    completed_at = _now_iso()
    store.complete_run(
        run_id=run_id,
        completed_at=completed_at,
        item_count=item_count,
        chunk_count=chunk_count,
    )
    if activate:
        store.activate_run(run_id)
    log.info(
        "indexing.run.complete",
        run_id=run_id, item_count=item_count, chunk_count=chunk_count,
        new_vectors=new_vector_count,
    )
    return IndexResult(
        run_id=run_id,
        item_count=item_count,
        chunk_count=chunk_count,
        new_vector_count=new_vector_count,
    )
