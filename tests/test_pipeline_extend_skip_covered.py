"""Extend mode must not re-extract a source it already covers (#48).

`run_indexing` used to call `adapter.get_text` for every source on every
run. Embedding was deduplicated, extraction was not, so a top-up re-parsed
the whole corpus to add a handful of chunks.

The fix skips extraction per source when that source already has chunks
and every one of them carries a vector for the run. Coverage does not
depend on iteration order, so it cannot reintroduce the ordering hazard
that removed the earlier `last_processed_key` fast-skip (#6).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
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


class _Provider:
    def __init__(self) -> None:
        self._metadata = EmbeddingMetadata(
            provider="gemini", model_name="gemini-embedding-001",
            model_version="v1", dimensions=4, normalized=True,
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
        self.embed_calls.append(list(texts))
        vectors = [
            pack_int8(np.array(
                [(hash(t + str(i)) % 256) - 128 for i in range(4)], dtype=np.int8,
            ))
            for t in texts
        ]
        return EmbeddingBatch(texts=texts, vectors=vectors, norms=None)

    def close(self) -> None:
        pass


class _CountingAdapter:
    """Yields configurable sources per item and counts get_text calls."""

    name = "test"
    version = "1"
    capabilities = frozenset({ItemKind.TEXT, ItemKind.METADATA})

    def __init__(self, sources: dict[str, list[tuple[str, str | None, str]]]) -> None:
        self._sources = sources
        self.get_text_calls: list[tuple[str, str, str | None]] = []

    def list_items(self, since=None) -> Iterator[Item]:
        for key in self._sources:
            yield Item(
                item_key=key, corpus="test", item_type="book",
                title=f"Item {key}", date=None, creators=[],
                abstract=None, metadata_hash=f"hash-{key}",
            )

    def get_sources(self, item: Item) -> Iterator[Source]:
        for stype, sref, _ in self._sources[item.item_key]:
            kind = ItemKind.METADATA if stype == "abstract" else ItemKind.TEXT
            yield Source(source_type=stype, source_ref=sref, kind=kind)

    def get_text(self, item: Item, source: Source) -> str | None:
        self.get_text_calls.append(
            (item.item_key, source.source_type, source.source_ref)
        )
        for stype, sref, text in self._sources[item.item_key]:
            if stype == source.source_type and sref == source.source_ref:
                return text
        return None

    def get_image(self, item: Item, source: Source) -> bytes | None:
        return None

    def close(self) -> None:
        pass


@pytest.fixture
def store(tmp_path: Path) -> Iterator[VectorStore]:
    s = VectorStore(tmp_path / "vectors.sqlite")
    yield s
    s.close()


def test_extend_does_not_extract_a_fully_covered_source(store: VectorStore) -> None:
    sources = {"A": [("pdf", "pdf:A1", "alpha text")]}
    first = run_indexing(
        adapter=_CountingAdapter(sources), store=store, provider=_Provider(),
    )

    second = _CountingAdapter(sources)
    result = run_indexing(
        adapter=second, store=store, provider=_Provider(),
        extend_run_id=first.run_id,
    )

    assert second.get_text_calls == []
    assert result.skipped_source_count == 1
    assert result.new_vector_count == 0


def test_a_new_source_on_a_covered_item_still_indexes(store: VectorStore) -> None:
    """The EPUB case. An item can be fully covered and still gain a source."""
    before = {"A": [("abstract", None, "alpha abstract")]}
    first = run_indexing(
        adapter=_CountingAdapter(before), store=store, provider=_Provider(),
    )

    after = {"A": [("abstract", None, "alpha abstract"),
                   ("epub", "epub:A1", "a whole book of text")]}
    second = _CountingAdapter(after)
    result = run_indexing(
        adapter=second, store=store, provider=_Provider(),
        extend_run_id=first.run_id,
    )

    assert ("A", "epub", "epub:A1") in second.get_text_calls
    assert ("A", "abstract", None) not in second.get_text_calls
    assert result.skipped_source_count == 1
    assert result.new_vector_count >= 1


def test_a_partially_vectorised_source_still_extracts(store: VectorStore) -> None:
    long_text = " ".join(f"word{i}" for i in range(600))
    sources = {"A": [("pdf", "pdf:A1", long_text)]}
    first = run_indexing(
        adapter=_CountingAdapter(sources), store=store, provider=_Provider(),
    )
    assert first.chunk_count > 1, "need multiple chunks for a partial-coverage test"

    # Drop one vector so the source is no longer fully covered.
    store._conn.execute(
        "DELETE FROM vectors WHERE vector_id = (SELECT MIN(vector_id) FROM vectors)"
    )
    store._conn.commit()

    second = _CountingAdapter(sources)
    result = run_indexing(
        adapter=second, store=store, provider=_Provider(),
        extend_run_id=first.run_id,
    )

    assert ("A", "pdf", "pdf:A1") in second.get_text_calls
    assert result.skipped_source_count == 0
    assert result.new_vector_count == 1


def test_rescan_forces_extraction_of_a_covered_source(store: VectorStore) -> None:
    sources = {"A": [("pdf", "pdf:A1", "alpha text")]}
    first = run_indexing(
        adapter=_CountingAdapter(sources), store=store, provider=_Provider(),
    )

    second = _CountingAdapter(sources)
    result = run_indexing(
        adapter=second, store=store, provider=_Provider(),
        extend_run_id=first.run_id, rescan=True,
    )

    assert ("A", "pdf", "pdf:A1") in second.get_text_calls
    assert result.skipped_source_count == 0


def test_a_fresh_run_always_extracts(store: VectorStore) -> None:
    """The skip is an extend-mode optimisation. A new run must not use it."""
    sources = {"A": [("pdf", "pdf:A1", "alpha text")]}
    run_indexing(adapter=_CountingAdapter(sources), store=store, provider=_Provider())

    second = _CountingAdapter(sources)
    result = run_indexing(adapter=second, store=store, provider=_Provider())

    assert ("A", "pdf", "pdf:A1") in second.get_text_calls
    assert result.skipped_source_count == 0
