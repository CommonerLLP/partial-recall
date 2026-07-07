"""Tests for the single-writer index lock."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from partial_recall.index.pipeline import run_indexing
from partial_recall.store.index_lock import (
    LOCK_SUFFIX,
    IndexLock,
    IndexLockHeldError,
)
from partial_recall.store.vector_store import VectorStore
from tests.test_pipeline import FakeEmbeddingProvider
from tests.test_pipeline_resumable import _Adapter


def _hold_externally(db_path: Path) -> sqlite3.Connection:
    """Take the lock the way ANOTHER PROCESS would: a raw EXCLUSIVE
    transaction on the lock file, invisible to this process's
    re-entrancy registry."""
    conn = sqlite3.connect(f"{Path(db_path).resolve()}{LOCK_SUFFIX}", timeout=0)
    conn.execute("BEGIN EXCLUSIVE")
    return conn


def test_acquire_fails_fast_when_other_process_holds(tmp_path: Path) -> None:
    db = tmp_path / "vectors.sqlite"
    other = _hold_externally(db)
    try:
        with pytest.raises(IndexLockHeldError):
            IndexLock(db).acquire()
    finally:
        other.close()


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


def test_probe_fails_fast_when_held_and_keeps_nothing(tmp_path: Path) -> None:
    """The CLI probes before expensive setup: a held lock raises, and a
    successful probe leaves the lock free for run_indexing to take."""
    db = tmp_path / "vectors.sqlite"
    other = _hold_externally(db)
    try:
        with pytest.raises(IndexLockHeldError):
            IndexLock(db).probe()
    finally:
        other.close()
    IndexLock(db).probe()
    with IndexLock(db):  # probe kept nothing — lock is acquirable
        pass


def test_run_indexing_fails_fast_under_held_lock(tmp_path: Path) -> None:
    """A second index process must fail fast with an actionable error,
    not silently duplicate embedding spend."""
    store = VectorStore(tmp_path / "vectors.sqlite")
    other = _hold_externally(store.db_path)
    try:
        with pytest.raises(IndexLockHeldError) as exc_info:
            run_indexing(
                adapter=_Adapter([("A", "alpha")]),
                store=store,
                provider=FakeEmbeddingProvider(),
            )
        assert exc_info.value.actionable_hint
    finally:
        other.close()
        store.close()


def test_run_indexing_releases_lock_after_completion(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "vectors.sqlite")
    try:
        run_indexing(
            adapter=_Adapter([("A", "alpha")]),
            store=store,
            provider=FakeEmbeddingProvider(),
        )
        other = _hold_externally(store.db_path)  # lock is free again
        other.close()
    finally:
        store.close()
