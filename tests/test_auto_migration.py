"""Tests for v0.2.4 auto-migration of existing DBs.

A DB created at schema_version=1 (the pre-v0.2.4 baseline) must
be upgraded forward to CURRENT_SCHEMA_VERSION when re-opened by
the v0.2.4+ codebase. Tests run a hand-rolled v1 schema first,
then open it via the normal `connect()` and assert the migration
ran and the FTS5 + Zotero-richness state is in place.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from partial_recall.errors import SchemaVersionMismatchError
from partial_recall.store.connection import connect
from partial_recall.store.schema import (
    CURRENT_SCHEMA_VERSION,
    load_migration,
)


def _create_v1_db(path: Path) -> None:
    """Lay down only the v0.0.1 (schema_version=1) tables — the
    baseline a user upgrading from a previous release would have."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(load_migration("0001_initial.sql"))
        conn.commit()
    finally:
        conn.close()


def test_auto_migration_brings_v1_db_to_current(tmp_path: Path) -> None:
    """An existing v1 DB → connect() runs 0002 + 0003 in order."""
    db = tmp_path / "v1.sqlite"
    _create_v1_db(db)

    conn_check = sqlite3.connect(db)
    pre = conn_check.execute(
        "SELECT schema_version FROM schema_meta LIMIT 1"
    ).fetchone()[0]
    conn_check.close()
    assert pre == 1

    # Auto-migration happens here.
    conn = connect(db)
    try:
        post = conn.execute(
            "SELECT schema_version FROM schema_meta LIMIT 1"
        ).fetchone()["schema_version"]
        assert post == CURRENT_SCHEMA_VERSION

        # 0002 effects
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' OR type='view'"
            ).fetchall()
        }
        assert "chunks_fts" in tables

        # 0003 effects — new columns on items + collections tables
        item_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(items)").fetchall()
        }
        assert "archive" in item_cols
        assert "archive_location" in item_cols
        assert "call_number" in item_cols
        assert "library_catalog" in item_cols
        assert "collections" in tables
        assert "item_collections" in tables
    finally:
        conn.close()


def test_no_op_when_db_already_current(tmp_path: Path) -> None:
    """A fresh DB created by connect() is at CURRENT_SCHEMA_VERSION;
    a second connect() must not re-run migrations."""
    db = tmp_path / "fresh.sqlite"
    conn1 = connect(db)
    v1 = conn1.execute(
        "SELECT schema_version FROM schema_meta LIMIT 1"
    ).fetchone()["schema_version"]
    conn1.close()

    conn2 = connect(db)
    v2 = conn2.execute(
        "SELECT schema_version FROM schema_meta LIMIT 1"
    ).fetchone()["schema_version"]
    conn2.close()

    assert v1 == CURRENT_SCHEMA_VERSION
    assert v2 == CURRENT_SCHEMA_VERSION


def test_db_at_future_version_refuses(tmp_path: Path) -> None:
    """A DB at version > CURRENT_SCHEMA_VERSION means the user is on
    older partial-recall than what wrote the DB — refuse with a clear
    error rather than silently downgrading."""
    db = tmp_path / "future.sqlite"
    _create_v1_db(db)
    # Pretend a future version stamped this DB.
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE schema_meta SET schema_version = ?",
        (CURRENT_SCHEMA_VERSION + 99,),
    )
    conn.commit()
    conn.close()

    with pytest.raises(SchemaVersionMismatchError, match="upgrade partial-recall"):
        connect(db)


def test_fts5_initial_population_from_existing_chunks(
    tmp_path: Path,
) -> None:
    """Auto-migration on a DB with chunks already inserted must
    populate chunks_fts with those previews."""
    db = tmp_path / "v1_with_chunks.sqlite"
    _create_v1_db(db)
    # Seed minimal items + chunks at v1.
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO items (item_key, corpus, item_type, metadata_hash, "
        "last_indexed_at) VALUES ('K1', 'zotero', 'book', 'h', '2026-05-19')"
    )
    conn.execute(
        "INSERT INTO chunks (item_key, corpus, source_type, chunk_index, "
        "text_hash, text_preview, chunker_version, indexed_at) VALUES "
        "('K1', 'zotero', 'abstract', 0, 'th1', "
        "'the politics of memory and caste', 'cv1', '2026-05-19')"
    )
    conn.commit()
    conn.close()

    upgraded = connect(db)
    try:
        rows = upgraded.execute(
            "SELECT text_preview FROM chunks_fts WHERE chunks_fts MATCH ?",
            ("memory",),
        ).fetchall()
    finally:
        upgraded.close()
    assert len(rows) == 1
    assert "memory" in rows[0]["text_preview"]


def test_fts5_triggers_keep_index_in_sync_with_chunks(
    tmp_path: Path,
) -> None:
    """Post-migration, inserting / deleting from chunks must be
    reflected automatically in chunks_fts via the triggers."""
    db = tmp_path / "fresh_with_fts.sqlite"
    conn = connect(db)
    try:
        conn.execute(
            "INSERT INTO items (item_key, corpus, item_type, metadata_hash, "
            "last_indexed_at) VALUES ('K2', 'zotero', 'book', 'h', '2026-05-19')"
        )
        conn.execute(
            "INSERT INTO chunks (item_key, corpus, source_type, chunk_index, "
            "text_hash, text_preview, chunker_version, indexed_at) VALUES "
            "('K2', 'zotero', 'note', 0, 'th2', "
            "'subaltern studies historiography', 'cv1', '2026-05-19')"
        )

        # Insert visible
        rows = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ?",
            ("subaltern",),
        ).fetchall()
        assert len(rows) == 1

        # Delete propagates
        conn.execute("DELETE FROM chunks WHERE item_key = 'K2'")
        rows_after = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ?",
            ("subaltern",),
        ).fetchall()
        assert rows_after == []
    finally:
        conn.close()
