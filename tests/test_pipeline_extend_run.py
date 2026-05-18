"""Tests for pipeline extend-run mode (v0.2.0 top-up path).

Validates:
  - extend mode skips chunks already vectorised in the target run
  - extend mode embeds chunks lacking a vector in the target run
  - extend mode picks up new items added to the corpus mid-life
  - run.is_active is preserved (not toggled) by an extend
  - run counts are recomputed from the vectors table
  - incompatible runs raise IncompatibleRunError:
        * vector-space mismatch always raises
        * provider/model identity mismatch raises unless waived
"""

from __future__ import annotations

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
from partial_recall.index.pipeline import (
    IncompatibleRunError,
    run_indexing,
)
from partial_recall.store.vector_store import VectorStore

# ---------------------------------------------------------------------------
# Provider + adapter doubles
# ---------------------------------------------------------------------------


class _Provider:
    """Configurable test embedder. Tracks embed-call counts for assertions."""

    def __init__(
        self,
        *,
        provider: str = "gemini",
        model_name: str = "gemini-embedding-001",
        dimensions: int = 4,
        normalized: bool = True,
        distance_metric: DistanceMetric = DistanceMetric.COSINE,
        quantization: Quantization = Quantization.INT8,
    ) -> None:
        self._metadata = EmbeddingMetadata(
            provider=provider,
            model_name=model_name,
            model_version="v1",
            dimensions=dimensions,
            normalized=normalized,
            distance_metric=distance_metric,
            max_input_tokens=512,
        )
        self._quantization = quantization
        self.embed_calls: list[list[str]] = []

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    @property
    def quantization(self) -> Quantization:
        return self._quantization

    def embed(
        self, texts: list[str], task: str = "search_document",
        batch_size: int | None = None,
    ) -> EmbeddingBatch:
        import numpy as np
        self.embed_calls.append(list(texts))
        vectors: list[bytes] = []
        for t in texts:
            arr = np.array(
                [(hash(t + str(i)) % 256) - 128 for i in range(self._metadata.dimensions)],
                dtype=np.int8,
            )
            vectors.append(pack_int8(arr))
        return EmbeddingBatch(texts=texts, vectors=vectors, norms=None)

    def close(self) -> None:
        pass

    @property
    def total_embedded(self) -> int:
        return sum(len(b) for b in self.embed_calls)


class _Adapter:
    """In-memory CorpusAdapter that yields a controllable set of items."""

    name = "test"
    version = "1"
    capabilities = frozenset({ItemKind.TEXT, ItemKind.METADATA})

    def __init__(self, items: list[tuple[str, str]]) -> None:
        # items: list of (item_key, source_text)
        self._items = [
            Item(
                item_key=key,
                corpus="test",
                item_type="book",
                title=f"Item {key}",
                date=None,
                creators=[],
                abstract=text,
                metadata_hash=f"hash-{key}",
            )
            for key, text in items
        ]

    def list_items(self, since=None) -> Iterator[Item]:
        yield from self._items

    def get_sources(self, item: Item) -> Iterator[Source]:
        yield Source(source_type="abstract", source_ref=None, kind=ItemKind.METADATA)

    def get_text(self, item: Item, source: Source) -> str | None:
        return item.abstract

    def get_image(self, item: Item, source: Source) -> bytes | None:
        return None

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[VectorStore]:
    s = VectorStore(tmp_path / "vectors.sqlite")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extend_run_skips_already_vectorised_chunks(store: VectorStore) -> None:
    adapter = _Adapter([("A", "alpha"), ("B", "bravo")])
    provider = _Provider()
    first = run_indexing(adapter=adapter, store=store, provider=provider)
    assert not first.extended
    embedded_first = provider.total_embedded
    assert embedded_first >= 2

    # Re-run with extend mode → nothing new should be embedded.
    provider2 = _Provider()
    result = run_indexing(
        adapter=adapter, store=store, provider=provider2,
        extend_run_id=first.run_id,
    )
    assert result.extended is True
    assert result.run_id == first.run_id
    assert result.new_vector_count == 0
    assert provider2.total_embedded == 0
    assert result.skipped_chunk_count >= 2


def test_extend_run_embeds_new_items_only(store: VectorStore) -> None:
    initial = _Adapter([("A", "alpha")])
    provider = _Provider()
    first = run_indexing(adapter=initial, store=store, provider=provider)
    initial_embedded = provider.total_embedded

    # Add a new item; extend.
    expanded = _Adapter([("A", "alpha"), ("B", "bravo"), ("C", "charlie")])
    provider2 = _Provider()
    result = run_indexing(
        adapter=expanded, store=store, provider=provider2,
        extend_run_id=first.run_id,
    )
    assert result.extended is True
    # Only the two new items' chunks were embedded.
    assert provider2.total_embedded == 2
    assert result.new_vector_count == 2
    assert result.chunk_count == 2  # 2 new chunks inserted
    assert result.skipped_chunk_count == 1  # original A skipped

    # Total vectors in run = 1 (from first) + 2 (top-up) = 3.
    n = store._conn.execute(
        "SELECT COUNT(*) AS n FROM vectors WHERE run_id = ?",
        (first.run_id,),
    ).fetchone()["n"]
    assert n == 3
    # Provider sanity: first run embedded 1, extend embedded 2.
    assert initial_embedded == 1


def test_extend_run_preserves_active_state(store: VectorStore) -> None:
    adapter = _Adapter([("A", "alpha")])
    first = run_indexing(adapter=adapter, store=store, provider=_Provider())
    active_before = store.get_active_run()
    assert active_before is not None
    assert active_before.run_id == first.run_id
    assert active_before.is_active is True

    run_indexing(
        adapter=_Adapter([("A", "alpha"), ("B", "bravo")]),
        store=store,
        provider=_Provider(),
        extend_run_id=first.run_id,
    )
    active_after = store.get_active_run()
    assert active_after is not None
    assert active_after.run_id == first.run_id  # still the same active run
    assert active_after.is_active is True


def test_extend_run_recomputes_counts(store: VectorStore) -> None:
    first = run_indexing(
        adapter=_Adapter([("A", "alpha")]),
        store=store, provider=_Provider(),
    )
    # Sanity: post-first-run counts equal what was indexed.
    row = store._conn.execute(
        "SELECT item_count, chunk_count FROM embedding_runs WHERE run_id = ?",
        (first.run_id,),
    ).fetchone()
    assert row["chunk_count"] == 1
    assert row["item_count"] == 1

    run_indexing(
        adapter=_Adapter([("A", "alpha"), ("B", "bravo"), ("C", "charlie")]),
        store=store, provider=_Provider(),
        extend_run_id=first.run_id,
    )
    row = store._conn.execute(
        "SELECT item_count, chunk_count FROM embedding_runs WHERE run_id = ?",
        (first.run_id,),
    ).fetchone()
    assert row["item_count"] == 3
    assert row["chunk_count"] == 3


def test_extend_run_vector_space_mismatch_raises(store: VectorStore) -> None:
    first = run_indexing(
        adapter=_Adapter([("A", "alpha")]),
        store=store, provider=_Provider(dimensions=4),
    )
    # Try to extend with a different-dim provider — vector-space fail.
    bigger = _Provider(dimensions=8)
    with pytest.raises(IncompatibleRunError, match="dimensions"):
        run_indexing(
            adapter=_Adapter([("A", "alpha"), ("B", "bravo")]),
            store=store, provider=bigger,
            extend_run_id=first.run_id,
        )


def test_extend_run_provider_identity_mismatch_raises_by_default(
    store: VectorStore,
) -> None:
    first = run_indexing(
        adapter=_Adapter([("A", "alpha")]),
        store=store,
        provider=_Provider(provider="cookjohn-imported", model_name="gemini-embedding-001"),
    )
    fresh_gemini = _Provider(provider="gemini", model_name="gemini-embedding-001")
    with pytest.raises(IncompatibleRunError, match="provider/model identity"):
        run_indexing(
            adapter=_Adapter([("A", "alpha"), ("B", "bravo")]),
            store=store, provider=fresh_gemini,
            extend_run_id=first.run_id,
        )


def test_extend_run_provider_identity_mismatch_waived_succeeds(
    store: VectorStore,
) -> None:
    """The cookjohn-imported → gemini bridge: same vector space, different
    provider label. Waiver is the expected escape hatch."""
    first = run_indexing(
        adapter=_Adapter([("A", "alpha")]),
        store=store,
        provider=_Provider(provider="cookjohn-imported", model_name="gemini-embedding-001"),
    )
    fresh_gemini = _Provider(provider="gemini", model_name="gemini-embedding-001")
    result = run_indexing(
        adapter=_Adapter([("A", "alpha"), ("B", "bravo")]),
        store=store, provider=fresh_gemini,
        extend_run_id=first.run_id,
        allow_provider_mismatch=True,
    )
    assert result.extended is True
    assert result.run_id == first.run_id
    assert result.new_vector_count == 1  # B was new; A was skipped


def test_extend_run_id_not_found_raises(store: VectorStore) -> None:
    with pytest.raises(IncompatibleRunError, match="not found"):
        run_indexing(
            adapter=_Adapter([("A", "alpha")]),
            store=store, provider=_Provider(),
            extend_run_id=999,
        )
