"""Single-writer advisory lock for indexing runs.

One `index` / `index --extend` writer per vector DB. The lock is an
EXCLUSIVE transaction held on a tiny sibling SQLite file
(`<db>.indexlock`) for the lifetime of the run:

- crash-safe: the OS releases SQLite's file lock when the process dies,
  so there is no stale-lockfile state to detect or repair;
- cross-platform: SQLite implements the locking on POSIX and Windows;
- zero dependencies.

The extend-mode insert paths stay race-tolerant (insert_vector_if_absent,
insert_chunk_if_absent) as a second line of defence: the lock is advisory
and does not reach across machines sharing a DB over a network filesystem.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from partial_recall.errors import PartialRecallError

LOCK_SUFFIX = ".indexlock"


class IndexLockHeldError(PartialRecallError):
    actionable_hint = (
        "Another `partial-recall index` process is writing to this vector DB. "
        "Wait for it to finish (or stop it), then rerun. Concurrent runs "
        "duplicate embedding spend without adding vectors."
    )


class IndexLock:
    """Holds the single-writer lock for one vector DB. Context manager."""

    def __init__(self, db_path: Path) -> None:
        self._lock_path = Path(f"{Path(db_path).resolve()}{LOCK_SUFFIX}")
        self._conn: sqlite3.Connection | None = None

    def acquire(self) -> None:
        conn = sqlite3.connect(self._lock_path, timeout=0)
        try:
            conn.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            conn.close()
            raise IndexLockHeldError(
                f"index lock is held by another process ({self._lock_path})"
            ) from exc
        self._conn = conn

    def probe(self) -> None:
        """Fail fast if another process holds the lock; do not keep it.

        For callers with expensive setup ahead of run_indexing (the CLI
        loads a ~470 MB ONNX model and opens/migrates the store): probe
        first so the common collision fails before that spend. The run
        itself is still serialized by run_indexing's own acquire — a
        writer arriving inside the probe-to-run window is caught there.
        """
        self.acquire()
        self.release()

    def release(self) -> None:
        if self._conn is not None:
            self._conn.rollback()
            self._conn.close()
            self._conn = None

    def __enter__(self) -> IndexLock:
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()
