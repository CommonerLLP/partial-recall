"""Tests for v0.2.2 resumable indexing (B4 + B5).

The contract:

  * After each item is fully processed (all sources → chunks → vectors
    written), the pipeline writes the item_key to indexing_progress.
  * On a clean completion, indexing_progress for that run is cleared.
  * SIGINT / SIGTERM mid-run finishes the current batch flush, writes
    progress, returns IndexResult(interrupted=True, last_processed_key=…).
  * On resume (re-run with extend_run_id), the pipeline re-walks every
    item — *no* fast-skip by item_key, because adapters do not
    guarantee sorted iteration order. The chunk-level vector_exists
    dedup is the cost-saving mechanism: items get walked again but
    nothing is re-embedded.
"""

from __future__ import annotations

import signal
from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.chunk.recursive_char import CHUNKER_VERSION
from partial_recall.corpus.types import Item, ItemKind, Source
from partial_recall.embedding.quantize import pack_int8
from partial_recall.embedding.types import (
    DistanceMetric,
    EmbeddingBatch,
    EmbeddingMetadata,
    Quantization,
)
from partial_recall.index.pipeline import run_indexing
from partial_recall.store.vector_store import VectorStore

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _Provider:
    def __init__(self) -> None:
        self._metadata = EmbeddingMetadata(
            provider="fake", model_name="fake-m", model_version="v",
            dimensions=4, normalized=True,
            distance_metric=DistanceMetric.COSINE, max_input_tokens=512,
        )
        self.embed_calls: list[list[str]] = []

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    @property
    def quantization(self) -> Quantization:
        return Quantization.INT8

    def embed(self, texts: list[str], task: str = "search_document",
              batch_size: int | None = None) -> EmbeddingBatch:
        import numpy as np
        self.embed_calls.append(list(texts))
        vectors: list[bytes] = []
        for t in texts:
            arr = np.array(
                [(hash(t + str(i)) % 256) - 128 for i in range(4)],
                dtype=np.int8,
            )
            vectors.append(pack_int8(arr))
        return EmbeddingBatch(texts=texts, vectors=vectors, norms=None)

    def close(self) -> None:
        pass


class _Adapter:
    name = "test"
    version = "1"
    capabilities = frozenset({ItemKind.TEXT, ItemKind.METADATA})

    def __init__(self, items: list[tuple[str, str]]) -> None:
        self._items = [
            Item(
                item_key=key, corpus="test", item_type="book",
                title=f"Item {key}", date=None, creators=[],
                abstract=text, metadata_hash=f"hash-{key}",
            )
            for key, text in items
        ]

    def list_items(self, since=None) -> Iterator[Item]:
        yield from self._items

    def count_items(self, since=None) -> int:
        return len(self._items)

    def get_sources(self, item: Item) -> Iterator[Source]:
        yield Source(source_type="abstract", source_ref=None, kind=ItemKind.METADATA)

    def get_text(self, item: Item, source: Source) -> str | None:
        return item.abstract

    def get_image(self, item: Item, source: Source) -> bytes | None:
        return None

    def close(self) -> None:
        pass


class _InterruptingAdapter(_Adapter):
    """Raises SIGINT to ourselves after yielding N items, so the
    pipeline's installed signal handler fires mid-run."""

    def __init__(self, items: list[tuple[str, str]], interrupt_after: int) -> None:
        super().__init__(items)
        self._interrupt_after = interrupt_after

    def list_items(self, since=None) -> Iterator[Item]:
        for idx, item in enumerate(self._items):
            yield item
            if idx + 1 == self._interrupt_after:
                # In-process signal delivery — works on both POSIX and
                # Windows. (os.kill(pid, SIGINT) is unreliable on
                # Windows, where it can terminate the process instead
                # of invoking the registered handler.)
                signal.raise_signal(signal.SIGINT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[VectorStore]:
    s = VectorStore(tmp_path / "vectors.sqlite")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Progress-tracking tests
# ---------------------------------------------------------------------------


def test_indexing_progress_written_per_item(store: VectorStore) -> None:
    adapter = _Adapter([("A", "alpha"), ("B", "bravo")])
    result = run_indexing(adapter=adapter, store=store, provider=_Provider())
    # On clean completion, progress is CLEARED (so a future re-run
    # walks the whole corpus and picks up any newly-added items).
    assert store.get_indexing_progress(result.run_id) is None
    assert not result.interrupted


def test_indexing_progress_kept_on_interrupt(store: VectorStore) -> None:
    """SIGINT mid-run: pipeline returns interrupted=True with a
    last_processed_key, and indexing_progress is persisted so resume
    can fast-skip."""
    adapter = _InterruptingAdapter(
        [("A", "alpha"), ("B", "bravo"), ("C", "charlie"), ("D", "delta")],
        interrupt_after=2,
    )
    result = run_indexing(adapter=adapter, store=store, provider=_Provider())
    assert result.interrupted is True
    # B was the second item; its work was flushed + progress written
    # before the signal-handler-checked break on the next iteration.
    assert result.last_processed_key == "B"
    persisted = store.get_indexing_progress(result.run_id)
    assert persisted == "B"


def test_resume_re_embeds_only_missing_chunks(
    store: VectorStore,
) -> None:
    """A second extend-mode call after an interrupt re-walks every
    item but embeds only the ones whose chunks are not yet in
    vectors. Correctness comes from chunk-level vector_exists, not
    from item-key sorting (which adapters do not guarantee)."""
    # First pass: interrupted after B.
    first_provider = _Provider()
    interrupting = _InterruptingAdapter(
        [("A", "alpha"), ("B", "bravo"), ("C", "charlie"), ("D", "delta")],
        interrupt_after=2,
    )
    first = run_indexing(
        adapter=interrupting, store=store, provider=first_provider,
    )
    assert first.interrupted

    # Resume: extend the same run with a fresh provider; A + B are
    # already vectorised so vector_exists skips them; only C + D get
    # new embedding calls.
    second_provider = _Provider()
    full_adapter = _Adapter([
        ("A", "alpha"), ("B", "bravo"),
        ("C", "charlie"), ("D", "delta"),
    ])
    second = run_indexing(
        adapter=full_adapter,
        store=store,
        provider=second_provider,
        extend_run_id=first.run_id,
        allow_provider_mismatch=False,
    )
    assert not second.interrupted
    embedded_texts: list[str] = []
    for batch in second_provider.embed_calls:
        embedded_texts.extend(batch)
    assert sorted(embedded_texts) == ["charlie", "delta"]
    # Progress cleared on clean completion.
    assert store.get_indexing_progress(first.run_id) is None


def test_resume_correct_even_when_adapter_yields_unsorted_order(
    store: VectorStore,
) -> None:
    """Regression for chatgpt-codex-connector P1 review on PR #6:
    fast-skip by item_key would silently drop items that yield after
    a 'larger' key. This test exercises an out-of-order adapter and
    confirms no item is ever silently skipped."""
    # First pass: interrupt after B. Order BACA-style.
    first_provider = _Provider()
    interrupting = _InterruptingAdapter(
        [("B", "bravo"), ("D", "delta"), ("A", "alpha"), ("C", "charlie")],
        interrupt_after=2,  # B + D processed
    )
    first = run_indexing(
        adapter=interrupting, store=store, provider=first_provider,
    )
    assert first.interrupted
    # Last processed item is the second one yielded — D.
    assert first.last_processed_key == "D"

    # Resume with full unsorted adapter. A and C still need embedding.
    # A sorts BEFORE D — a naïve fast-skip would drop A. Must not.
    second_provider = _Provider()
    run_indexing(
        adapter=_Adapter([
            ("B", "bravo"), ("D", "delta"),
            ("A", "alpha"), ("C", "charlie"),
        ]),
        store=store, provider=second_provider,
        extend_run_id=first.run_id,
    )
    embedded = []
    for batch in second_provider.embed_calls:
        embedded.extend(batch)
    assert sorted(embedded) == ["alpha", "charlie"]


def test_resume_chunk_dedup_still_catches_items_below_progress(
    store: VectorStore,
) -> None:
    """Defence-in-depth: if for any reason fast-skip misses an item,
    chunk-level vector_exists still prevents re-embedding cost."""
    # Build a state where progress points to "B" but B's chunks ARE
    # already in vectors. Re-running should not re-embed B even
    # though fast-skip would also catch it.
    first_provider = _Provider()
    interrupting = _InterruptingAdapter(
        [("A", "alpha"), ("B", "bravo"), ("C", "charlie")],
        interrupt_after=2,
    )
    first = run_indexing(
        adapter=interrupting, store=store, provider=first_provider,
    )
    assert first.last_processed_key == "B"

    # Manually clear progress so fast-skip is bypassed — to prove the
    # chunk-level dedup still keeps the run cheap.
    store.clear_indexing_progress(first.run_id)

    second_provider = _Provider()
    second = run_indexing(
        adapter=_Adapter([("A", "alpha"), ("B", "bravo"), ("C", "charlie")]),
        store=store, provider=second_provider,
        extend_run_id=first.run_id,
    )
    embedded_texts: list[str] = []
    for batch in second_provider.embed_calls:
        embedded_texts.extend(batch)
    # Only C is new; A and B are skipped by vector_exists even with
    # no progress hint.
    assert embedded_texts == ["charlie"]
    assert second.skipped_chunk_count == 2  # A + B chunks already vectorised


def test_signal_handlers_restored_after_run(store: VectorStore) -> None:
    """Pipeline must restore previous SIGINT / SIGTERM handlers on
    exit, so callers (tests, embedding daemons) keep their own
    handler installations intact."""
    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    run_indexing(
        adapter=_Adapter([("A", "alpha")]),
        store=store, provider=_Provider(),
    )
    assert signal.getsignal(signal.SIGINT) == previous_sigint
    assert signal.getsignal(signal.SIGTERM) == previous_sigterm


# ---------------------------------------------------------------------------
# Concurrent-writer race
# ---------------------------------------------------------------------------


class _RacingProvider(_Provider):
    """Simulates a concurrent index process: while this process waits on
    the embedding call, the other writer commits vectors for the very
    chunks queued in this flush. The queue-time vector_exists guard has
    already passed, so without an idempotent insert the flush dies on
    the vectors (chunk_id, run_id) UNIQUE constraint."""

    def __init__(self, store: VectorStore, run_id: int) -> None:
        super().__init__()
        self._store = store
        self._run_id = run_id

    def embed(self, texts: list[str], task: str = "search_document",
              batch_size: int | None = None) -> EmbeddingBatch:
        import numpy as np
        batch = super().embed(texts, task=task, batch_size=batch_size)
        found = self._store.find_chunk_id(
            item_key="B", corpus="test", source_type="abstract",
            source_ref=None, chunk_index=0,
            chunker_version=CHUNKER_VERSION, text_hash="",
        )
        if found is not None:
            chunk_id, _ = found
            if not self._store.vector_exists(chunk_id, self._run_id):
                self._store.insert_vector(
                    chunk_id=chunk_id, run_id=self._run_id,
                    vector=pack_int8(np.array([1, 2, 3, 4], dtype=np.int8)),
                    norm=None, indexed_at="2026-01-01T00:00:00+00:00",
                )
        return batch


def test_extend_survives_concurrent_writer_race(store: VectorStore) -> None:
    """Two `index --extend` processes on the same run race between
    the queue-time vector_exists check and the flush. The loser
    must skip the already-present vector and finish, not crash."""
    first = run_indexing(
        adapter=_Adapter([("A", "alpha")]), store=store, provider=_Provider(),
    )
    result = run_indexing(
        adapter=_Adapter([("A", "alpha"), ("B", "bravo")]),
        store=store,
        provider=_RacingProvider(store, first.run_id),
        extend_run_id=first.run_id,
    )
    assert result.extended
    assert not result.interrupted
    # The raced vector was not double-inserted and not double-counted.
    assert result.new_vector_count == 0
    found = store.find_chunk_id(
        item_key="B", corpus="test", source_type="abstract",
        source_ref=None, chunk_index=0,
        chunker_version=CHUNKER_VERSION, text_hash="",
    )
    assert found is not None
    rows = list(store._conn.execute(
        "SELECT COUNT(*) AS n FROM vectors WHERE chunk_id = ? AND run_id = ?",
        (found[0], first.run_id),
    ))
    assert rows[0]["n"] == 1


class _StaleFindStore(VectorStore):
    """Simulates the chunk-insert race window: a concurrent extend
    writer commits item B's chunk between this process's find_chunk_id
    (which saw nothing) and its insert. Modeled by serving one stale
    None for item B even though the row already exists."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._stale_served = False

    def find_chunk_id(self, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("item_key") == "B" and not self._stale_served:
            self._stale_served = True
            return None
        return super().find_chunk_id(**kwargs)


class _RefAdapter(_Adapter):
    """Adapter whose sources carry a non-NULL source_ref — the case
    where the chunks identity UNIQUE constraint actually bites (SQLite
    unique indexes treat NULL source_ref values as distinct rows)."""

    def get_sources(self, item: Item) -> Iterator[Source]:
        yield Source(source_type="abstract", source_ref="abs:0", kind=ItemKind.METADATA)


def test_extend_survives_concurrent_chunk_insert_race(tmp_path: Path) -> None:
    """Two `index --extend` processes race on creating the same new
    chunk. The loser must adopt the winner's row and finish, not die
    on the chunks identity UNIQUE constraint."""
    from partial_recall.index.pipeline import _now_iso, _text_hash

    store = _StaleFindStore(tmp_path / "vectors.sqlite")
    try:
        first = run_indexing(
            adapter=_RefAdapter([("A", "alpha")]), store=store, provider=_Provider(),
        )
        # The concurrent winner has already committed item B and its chunk
        # (but not yet its vector) when the loser reaches insert time.
        store.upsert_item(
            item_key="B", corpus="test", item_type="book",
            title="Item B", date=None, creators_json="[]", abstract="bravo",
            metadata_hash="hash-B", last_indexed_at=_now_iso(),
            corpus_ref=None,
        )
        store.insert_chunk(
            item_key="B", corpus="test", source_type="abstract",
            source_ref="abs:0", chunk_index=0,
            char_offset_start=0, char_offset_end=5,
            text_hash=_text_hash("bravo"), text_preview="bravo",
            chunker_version=CHUNKER_VERSION, detected_locale=None,
            indexed_at=_now_iso(),
        )
        result = run_indexing(
            adapter=_RefAdapter([("A", "alpha"), ("B", "bravo")]),
            store=store,
            provider=_Provider(),
            extend_run_id=first.run_id,
        )
        assert result.extended
        assert not result.interrupted
        # The raced chunk was adopted, not re-created or double-counted.
        assert result.chunk_count == 0
        rows = list(store._conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE item_key = 'B'",
        ))
        assert rows[0]["n"] == 1
        # The winner had not embedded yet, so the loser supplies the vector.
        assert result.new_vector_count == 1
    finally:
        store.close()
