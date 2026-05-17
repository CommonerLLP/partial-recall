"""Connection helpers for partial-recall's SQLite vector store.

Applies PRAGMAs on every connect; runs migrations on schema-version mismatch.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from partial_recall.errors import SchemaVersionMismatchError, VectorStoreError
from partial_recall.paths import ensure_parent_directory
from partial_recall.store.schema import (
    CURRENT_SCHEMA_VERSION,
    list_migrations,
    load_migration,
)

_PRAGMAS = (
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA cache_size = -65536;",
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA mmap_size = 268435456;",
    "PRAGMA foreign_keys = ON;",
)


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection, apply PRAGMAs, ensure schema up to date.

    If the DB does not exist, it is created and migrations are applied.
    If the DB exists with an older schema_version, raise (auto-migration
    deferred to v0.1.0).
    """
    ensure_parent_directory(db_path)
    is_new = not db_path.exists()
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    if is_new:
        _apply_all_migrations(conn)
    else:
        _verify_schema_version(conn)
    return conn


def _apply_all_migrations(conn: sqlite3.Connection) -> None:
    for filename in list_migrations():
        sql = load_migration(filename)
        conn.executescript(sql)


def _verify_schema_version(conn: sqlite3.Connection) -> None:
    try:
        row = conn.execute(
            "SELECT schema_version FROM schema_meta LIMIT 1"
        ).fetchone()
    except sqlite3.Error as e:
        raise VectorStoreError(
            f"cannot read schema_meta from vector DB; is this a partial-recall DB? ({e})"
        ) from e
    if row is None:
        raise VectorStoreError("schema_meta table is empty")
    version = int(row["schema_version"])
    if version < CURRENT_SCHEMA_VERSION:
        raise SchemaVersionMismatchError(
            f"DB schema version {version} < expected {CURRENT_SCHEMA_VERSION}; "
            f"auto-migration is a v0.1.0 feature"
        )
    if version > CURRENT_SCHEMA_VERSION:
        raise SchemaVersionMismatchError(
            f"DB schema version {version} > supported {CURRENT_SCHEMA_VERSION}; "
            f"upgrade partial-recall"
        )
