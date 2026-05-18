"""Tests for v0.2.2 resumable indexing (B4 + B5).

The contract:

  * After each item is fully processed (all sources → chunks → vectors
    written), the pipeline writes the item_key to indexing_progress.
  * On a clean completion, indexing_progress for that run is cleared.
  * SIGINT / SIGTERM mid-run finishes the current batch flush, writes
    progress, returns IndexResult(interrupted=True, last_processed_key=…).
  * On resume (re-run with extend_run_id), items whose item_key sorts
    at or before last_processed_key are fast-skipped — chunk-level
    dedup still catches anything that slipped through.
"""

from __future__ import annotations

import signal
from collections.abc import Iterator
from pathlib import Path

import pytest

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
        import os
        for idx, item in enumerate(self._items):
            yield item
            if idx + 1 == self._interrupt_after:
                # Send SIGINT to self; the pipeline's handler should
                # catch it and request a clean stop.
                os.kill(os.getpid(), signal.SIGINT)


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


def test_resume_fast_skips_items_at_or_below_last_processed(
    store: VectorStore,
) -> None:
    """A second extend-mode call after an interrupt should not re-walk
    items already known done."""
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

    # Resume: extend the same run with a fresh provider; expect only
    # C + D embedded (A + B fast-skipped).
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
    # New embeddings only for C + D (1 chunk each).
    embedded_texts: list[str] = []
    for batch in second_provider.embed_calls:
        embedded_texts.extend(batch)
    assert sorted(embedded_texts) == ["charlie", "delta"]
    # Progress cleared on clean completion.
    assert store.get_indexing_progress(first.run_id) is None


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
