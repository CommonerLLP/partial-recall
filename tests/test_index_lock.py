"""Tests for the single-writer index lock."""

from __future__ import annotations

from pathlib import Path

import pytest

from partial_recall.index.pipeline import run_indexing
from partial_recall.store.index_lock import IndexLock, IndexLockHeldError
from partial_recall.store.vector_store import VectorStore
from tests.test_pipeline import FakeEmbeddingProvider
from tests.test_pipeline_resumable import _Adapter


def test_second_acquire_fails_fast(tmp_path: Path) -> None:
    db = tmp_path / "vectors.sqlite"
    with IndexLock(db), pytest.raises(IndexLockHeldError):
        IndexLock(db).acquire()


def test_lock_released_on_exit(tmp_path: Path) -> None:
    db = tmp_path / "vectors.sqlite"
    with IndexLock(db):
        pass
    with IndexLock(db):  # reacquirable — no stale state left behind
        pass


def test_lock_released_on_exception(tmp_path: Path) -> None:
    db = tmp_path / "vectors.sqlite"
    with pytest.raises(RuntimeError), IndexLock(db):
        raise RuntimeError("indexing blew up")
    with IndexLock(db):
        pass


def test_run_indexing_fails_fast_under_held_lock(tmp_path: Path) -> None:
    """A second index process must fail fast with an actionable error,
    not silently duplicate embedding spend."""
    store = VectorStore(tmp_path / "vectors.sqlite")
    try:
        # The outer IndexLock plays the "other" index process.
        with IndexLock(store.db_path), pytest.raises(IndexLockHeldError) as exc_info:
            run_indexing(
                adapter=_Adapter([("A", "alpha")]),
                store=store,
                provider=FakeEmbeddingProvider(),
            )
        assert exc_info.value.actionable_hint
    finally:
        store.close()


def test_run_indexing_releases_lock_after_completion(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "vectors.sqlite")
    try:
        run_indexing(
            adapter=_Adapter([("A", "alpha")]),
            store=store,
            provider=FakeEmbeddingProvider(),
        )
        with IndexLock(store.db_path):  # lock is free again
            pass
    finally:
        store.close()
