"""Connection helpers for partial-recall's SQLite vector store.

Applies PRAGMAs on every connect; runs migrations on schema-version
mismatch. v0.2.4 adds auto-migration support — an existing DB at a
lower schema_version gets the missing migrations applied forward.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import structlog

from partial_recall.errors import SchemaVersionMismatchError, VectorStoreError
from partial_recall.paths import ensure_parent_directory
from partial_recall.store.schema import (
    CURRENT_SCHEMA_VERSION,
    list_migrations,
    load_migration,
)

log = structlog.get_logger(__name__)

# Migration filenames look like "0002_fts5.sql". Parse the leading
# integer; ignore the descriptive suffix.
_MIGRATION_NUMBER_RE = re.compile(r"^(\d+)_")

_PRAGMAS = (
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA cache_size = -65536;",
    "PRAGMA temp_store = MEMORY;",
    "PRAGMA mmap_size = 268435456;",
    "PRAGMA foreign_keys = ON;",
)


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection, apply PRAGMAs, ensure schema is up to date.

    Three paths:
      * brand-new DB → apply every migration in order;
      * existing DB at schema_version < CURRENT_SCHEMA_VERSION → apply
        the missing migrations forward (auto-migration);
      * existing DB at exactly CURRENT_SCHEMA_VERSION → no-op;
      * existing DB at version > CURRENT → raise (user needs to
        upgrade partial-recall).
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
        _ensure_schema_current(conn, db_path=db_path)
    return conn


def _apply_all_migrations(conn: sqlite3.Connection) -> None:
    for filename in list_migrations():
        sql = load_migration(filename)
        conn.executescript(sql)


def _migration_version(filename: str) -> int | None:
    m = _MIGRATION_NUMBER_RE.match(filename)
    return int(m.group(1)) if m else None


def _ensure_schema_current(
    conn: sqlite3.Connection, *, db_path: Path
) -> None:
    """Auto-apply any pending migrations on an existing DB.

    Reads the current schema_version, then for every migration file
    whose leading number is greater than that, executes the script.
    Each migration is responsible for updating schema_meta itself
    (UPDATE schema_meta SET schema_version = N at the bottom of the
    file), so after the loop the version reflects what landed.
    """
    try:
        row = conn.execute(
            "SELECT schema_version FROM schema_meta LIMIT 1"
        ).fetchone()
    except sqlite3.Error as e:
        raise VectorStoreError(
            f"cannot read schema_meta from vector DB; is this a "
            f"partial-recall DB? ({e})"
        ) from e
    if row is None:
        raise VectorStoreError("schema_meta table is empty")
    current = int(row["schema_version"])

    if current > CURRENT_SCHEMA_VERSION:
        raise SchemaVersionMismatchError(
            f"DB schema version {current} > supported "
            f"{CURRENT_SCHEMA_VERSION}; upgrade partial-recall to read "
            f"this DB"
        )
    if current == CURRENT_SCHEMA_VERSION:
        return

    # Apply pending migrations in order.
    pending: list[tuple[int, str]] = []
    for filename in list_migrations():
        version_n = _migration_version(filename)
        if version_n is None:
            continue
        if version_n > current:
            pending.append((version_n, filename))

    if not pending:
        # Lower version reported but no migration files to bridge it.
        # That's a malformed state — surface it loudly.
        raise SchemaVersionMismatchError(
            f"DB at schema_version {current} but no migrations found "
            f"to bridge it to {CURRENT_SCHEMA_VERSION}"
        )

    log.info(
        "vector_store.migration.start",
        db_path=str(db_path),
        from_version=current,
        to_version=CURRENT_SCHEMA_VERSION,
        pending=[f for _, f in pending],
    )
    for version_n, filename in pending:
        log.info(
            "vector_store.migration.apply",
            filename=filename, to_version=version_n,
        )
        conn.executescript(load_migration(filename))

    # Confirm the migrations bumped schema_version correctly.
    final_row = conn.execute(
        "SELECT schema_version FROM schema_meta LIMIT 1"
    ).fetchone()
    final = int(final_row["schema_version"]) if final_row else None
    if final != CURRENT_SCHEMA_VERSION:
        raise VectorStoreError(
            f"migration ran but schema_version is {final!r} "
            f"(expected {CURRENT_SCHEMA_VERSION}); a migration script "
            f"is missing its `UPDATE schema_meta SET schema_version = N`"
        )
    log.info(
        "vector_store.migration.complete",
        db_path=str(db_path),
        schema_version=final,
    )
