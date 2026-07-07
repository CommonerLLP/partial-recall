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
        self._lock_path = Path(f"{db_path}{LOCK_SUFFIX}")
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
