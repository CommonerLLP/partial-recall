"""Indexing pipeline: walk corpus → extract → chunk → embed → store.

Two modes:

* **New-run mode** (default): create a fresh `embedding_run`; embed every
  chunk encountered into it. Idempotent for chunks (text_hash dedup).

* **Extend-run mode** (`extend_run_id` set): re-use an existing run;
  embed only those chunks that lack a vector for that run. This is the
  top-up path — adds new items + backfills any chunk that the original
  run didn't reach (e.g. a rehydrated import that stopped midway).

Idempotency: chunks are deduplicated via text_hash. In extend mode,
already-vectorised chunks are skipped without re-embedding.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import signal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from partial_recall.chunk.recursive_char import CHUNKER_VERSION, chunk_text
from partial_recall.corpus.protocol import CorpusAdapter
from partial_recall.corpus.types import Item
from partial_recall.embedding.protocol import EmbeddingProvider
from partial_recall.store.vector_store import VectorStore

# A progress callback receives: the current item, its 1-based index, and
# the total (None if the adapter can't say). Implementations should be
# cheap — they fire once per item.
ProgressCallback = Callable[[Item, int, int | None], None]

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IndexResult:
    run_id: int
    item_count: int
    chunk_count: int
    new_vector_count: int
    skipped_chunk_count: int = 0  # extend-run: chunks already vectorised
    extended: bool = False        # True if this was an extend-run pass
    interrupted: bool = False     # True if SIGINT/SIGTERM caused early exit
    last_processed_key: str | None = None  # set when interrupted


class IncompatibleRunError(ValueError):
    """Raised when an extend-run target is incompatible with the provider."""


class _InterruptFlag:
    """Mutable container set by signal handlers; checked between items.

    Avoids raising KeyboardInterrupt mid-batch (which would lose the
    pending Gemini-paid batch). The pipeline checks this between items
    and exits cleanly after the next flush.
    """

    def __init__(self) -> None:
        self.requested = False
        self.signal_name: str | None = None

    def request(self, signum: int, _frame: object) -> None:
        self.requested = True
        try:
            self.signal_name = signal.Signals(signum).name
        except (ValueError, AttributeError):  # noqa: BLE001 — defensive
            self.signal_name = f"signal-{signum}"


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
    extend_run_id: int | None = None,
    allow_provider_mismatch: bool = False,
    on_item_start: ProgressCallback | None = None,
) -> IndexResult:
    """Run an indexing pass.

    New-run mode (default): create a fresh `embedding_run`; embed every
    walked chunk into it.

    Extend-run mode (`extend_run_id` set): re-use that run; verify it is
    vector-space-compatible with the provider (dimensions, quantization,
    normalized, distance_metric); embed only chunks that lack a vector
    in that run. The provider/model_name check can be suppressed with
    `allow_provider_mismatch=True` — useful when extending an imported
    run (e.g. cookjohn-imported with model='gemini-embedding-001') with
    a fresh Gemini provider (provider='gemini', same model). Vector-space
    fields are always enforced.

    On completion of a new run, marks it active if `activate=True`.
    On completion of an extend, run counts are recomputed but the run's
    active/inactive state is left untouched.
    """
    extended = extend_run_id is not None
    started_at = _now_iso()
    meta = provider.metadata

    if extended:
        run = store.get_run(extend_run_id)  # type: ignore[arg-type]
        if run is None:
            raise IncompatibleRunError(f"extend-run target run_id={extend_run_id} not found")
        # Vector-space compatibility: hard requirement. If these differ,
        # vectors from the provider literally cannot live in the same space.
        space_mismatches: list[str] = []
        if run.dimensions != meta.dimensions:
            space_mismatches.append(
                f"dimensions: run={run.dimensions} provider={meta.dimensions}")
        if run.quantization != provider.quantization.value:
            space_mismatches.append(
                f"quantization: run={run.quantization} provider={provider.quantization.value}")
        if bool(run.normalized) != bool(meta.normalized):
            space_mismatches.append(
                f"normalized: run={run.normalized} provider={meta.normalized}")
        if run.distance_metric != meta.distance_metric.value:
            space_mismatches.append(
                f"distance_metric: run={run.distance_metric} provider={meta.distance_metric.value}")
        if space_mismatches:
            raise IncompatibleRunError(
                "extend-run vector-space mismatch: " + "; ".join(space_mismatches)
            )
        # Provider/model identity: soft check by default, hard if not waived.
        if not allow_provider_mismatch:
            ident_mismatches: list[str] = []
            if run.provider != meta.provider:
                ident_mismatches.append(
                    f"provider: run={run.provider!r} provider={meta.provider!r}")
            if run.model_name != meta.model_name:
                ident_mismatches.append(
                    f"model_name: run={run.model_name!r} provider={meta.model_name!r}")
            if ident_mismatches:
                raise IncompatibleRunError(
                    "extend-run provider/model identity mismatch ("
                    "pass allow_provider_mismatch=True to override): "
                    + "; ".join(ident_mismatches)
                )
        run_id = run.run_id
        log.info(
            "indexing.run.extend",
            run_id=run_id, provider=meta.provider, model=meta.model_name,
            allow_provider_mismatch=allow_provider_mismatch,
        )
    else:
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
    skipped_chunk_count = 0

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
            if extended:
                # Extend mode tolerates a concurrent index process: the
                # queue-time vector_exists guard cannot see vectors another
                # writer commits between queue time and this flush, and the
                # committed vector is equally valid.
                inserted = store.insert_vector_if_absent(
                    chunk_id=chunk_id,
                    run_id=run_id,
                    vector=vec,
                    norm=None,
                    indexed_at=_now_iso(),
                )
                if not inserted:
                    log.warning(
                        "indexing.vector.already_present",
                        chunk_id=chunk_id,
                        run_id=run_id,
                    )
                    continue
            else:
                # A fresh run owns its run_id exclusively; a collision here
                # is a pipeline bug and must surface, not be swallowed.
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

    total_items: int | None = None
    try:
        total_items = adapter.count_items()
    except Exception:  # noqa: BLE001 — progress is cosmetic; failure is non-fatal
        total_items = None

    # Install signal handlers so SIGINT (Ctrl-C) and SIGTERM finish the
    # current batch cleanly instead of losing in-flight Gemini-paid
    # work. We capture the previous handlers so the pipeline plays nice
    # with callers that install their own (tests, embedding daemons).
    interrupt = _InterruptFlag()
    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGINT, interrupt.request)
        signal.signal(signal.SIGTERM, interrupt.request)
    except (ValueError, OSError):
        # Not on the main thread, or signal module unavailable. Skip
        # signal-handling; the pipeline still runs, just without
        # graceful shutdown on Ctrl-C.
        pass

    # Track the last item whose chunks were ALL successfully embedded +
    # written for this run. Updated only at item boundaries, never
    # mid-source — so a saved last_processed_key always points at an
    # item whose work is fully durable in vectors.
    last_completed_key: str | None = None

    # We deliberately do NOT fast-skip by last_processed_key.
    #
    # An earlier draft skipped items with item_key <= last_processed_key
    # as an optimisation, but that's only safe when adapter iteration
    # is strictly sorted by item_key. ZoteroAdapter's SQL does not
    # ORDER BY anything; FolderAdapter iterates by filesystem walk
    # order. If A yields after B (legal under SQLite storage order),
    # a resume with last_processed_key='B' would silently skip A,
    # missing PDF extraction even if A was never processed.
    # (Caught by chatgpt-codex-connector review on PR #6.)
    #
    # Cost of removal: on resume, every item is re-walked and its
    # sources re-opened. The chunk_exists / vector_exists guards
    # still prevent re-embedding work — the bill stays cheap; only
    # PDF-extraction CPU is repeated. Acceptable in exchange for
    # correctness. Sorted-order fast-skip can return as a v0.2.x
    # enhancement once adapters declare ordering guarantees.
    _ = store.get_indexing_progress(run_id) if extended else None

    for item in adapter.list_items():
        item_count += 1
        if interrupt.requested:
            log.info("indexing.run.interrupt.requested",
                     signal=interrupt.signal_name,
                     last_completed_key=last_completed_key)
            break
        if on_item_start is not None:
            # Progress UI must never crash indexing.
            with contextlib.suppress(Exception):
                on_item_start(item, item_count, total_items)
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
            archive=item.archive,
            archive_location=item.archive_location,
            call_number=item.call_number,
            library_catalog=item.library_catalog,
        )
        # For each source: extract → chunk → record
        for source in adapter.get_sources(item):
            text = adapter.get_text(item, source)
            if not text:
                continue
            chunks = chunk_text(text)
            for chunk in chunks:
                th = _text_hash(chunk.text)
                preview = chunk.text[:400] if len(chunk.text) > 400 else chunk.text
                found = store.find_chunk_id(
                    item_key=item.item_key,
                    corpus=item.corpus,
                    source_type=source.source_type,
                    source_ref=source.source_ref,
                    chunk_index=chunk.chunk_index,
                    chunker_version=CHUNKER_VERSION,
                    text_hash=th,
                )
                content_changed = False
                if found is None:
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
                else:
                    chunk_id, stored_hash = found
                    content_changed = stored_hash != th
                # Extend mode: skip chunks that already have a vector in
                # this run. New-run mode: always embed (vectors table
                # enforces UNIQUE(chunk_id, run_id); a fresh run never
                # collides).
                if extended and store.vector_exists(chunk_id, run_id):
                    skipped_chunk_count += 1
                    continue
                # Defer metadata update until here — only update when we are
                # about to re-embed, so chunk text_hash/preview stays in sync
                # with the vector that will be written.
                if content_changed:
                    store.update_chunk_content(
                        chunk_id=chunk_id,
                        text_hash=th,
                        text_preview=preview,
                    )
                pending.append((chunk_id, chunk.text))
                if len(pending) >= batch_size:
                    flush_pending()

        # End of this item's sources. Force a flush so progress write
        # below reflects a fully-durable state — every chunk for this
        # item is in vectors before we mark the item complete.
        flush_pending()
        store.set_indexing_progress(
            run_id=run_id, last_processed_key=item.item_key
        )
        last_completed_key = item.item_key

    # Flush final batch (no-op if we just flushed at item boundary)
    flush_pending()

    # Detect interrupted exit BEFORE the "completion" path so we don't
    # mark the run as complete or activate it. Restore signal handlers
    # whether we exit cleanly or via interrupt.
    try:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
    except (ValueError, OSError):
        pass

    if interrupt.requested:
        log.warning(
            "indexing.run.interrupted",
            run_id=run_id,
            signal=interrupt.signal_name,
            last_completed_key=last_completed_key,
            walked_items=item_count,
            new_vectors=new_vector_count,
        )
        return IndexResult(
            run_id=run_id,
            item_count=item_count,
            chunk_count=chunk_count,
            new_vector_count=new_vector_count,
            skipped_chunk_count=skipped_chunk_count,
            extended=extended,
            interrupted=True,
            last_processed_key=last_completed_key,
        )

    # Clean-completion paths below: clear progress so the next run
    # walks the full corpus (fast-skip would otherwise treat the
    # last-processed-key from this run as authoritative, missing any
    # new items the user added that sort before it).
    store.clear_indexing_progress(run_id)

    if extended:
        # Recompute the run's totals from the vectors table so the count
        # reflects the post-top-up reality, not just this pass.
        total_items, total_chunks = store.recompute_run_counts(run_id)
        log.info(
            "indexing.run.extend.complete",
            run_id=run_id,
            walked_items=item_count, new_chunks=chunk_count,
            new_vectors=new_vector_count, skipped=skipped_chunk_count,
            total_items=total_items, total_chunks=total_chunks,
        )
        return IndexResult(
            run_id=run_id,
            item_count=item_count,
            chunk_count=chunk_count,
            new_vector_count=new_vector_count,
            skipped_chunk_count=skipped_chunk_count,
            extended=True,
        )

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
