"""Tests for the cookjohn importer."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.importers.cookjohn import ImportResult, import_cookjohn
from partial_recall.store.vector_store import VectorStore


@pytest.fixture
def cookjohn_db(fixtures_dir: Path) -> Path:
    return fixtures_dir / "cookjohn_snapshot" / "zotero-mcp-vectors.sqlite"


@pytest.fixture
def zotero_db(fixtures_dir: Path) -> Path:
    return fixtures_dir / "zotero_snapshot" / "zotero.sqlite"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[VectorStore]:
    s = VectorStore(tmp_path / "vectors.sqlite")
    yield s
    s.close()


def test_import_creates_run(cookjohn_db: Path, store: VectorStore) -> None:
    result = import_cookjohn(
        cookjohn_path=cookjohn_db,
        zotero_path=None,
        store=store,
        activate=True,
    )
    assert isinstance(result, ImportResult)
    assert result.item_count == 2  # ITEM01XX + ITEM02XX
    assert result.chunk_count == 3  # 2 + 1
    assert result.vector_count == 3
    active = store.get_active_run()
    assert active is not None
    assert active.run_id == result.run_id
    assert active.provider == "cookjohn-imported"
    assert active.model_name == "gemini-embedding-001"
    assert active.dimensions == 3072


def test_import_with_zotero_enrichment(
    cookjohn_db: Path, zotero_db: Path, store: VectorStore
) -> None:
    import_cookjohn(
        cookjohn_path=cookjohn_db,
        zotero_path=zotero_db,
        store=store,
    )
    rows = list(store._conn.execute("SELECT item_key, title FROM items ORDER BY item_key"))
    titles = {r["item_key"]: r["title"] for r in rows}
    assert titles["ITEM01XX"] == "Library policy in India: a history"
    assert (
        titles["ITEM02XX"]
        == "The Chattopadhyaya Committee report on national library policy"
    )


def test_import_is_idempotent(cookjohn_db: Path, store: VectorStore) -> None:
    """Re-running import on the same data doesn't duplicate chunks."""
    import_cookjohn(cookjohn_path=cookjohn_db, zotero_path=None, store=store)
    import_cookjohn(cookjohn_path=cookjohn_db, zotero_path=None, store=store)
    # Two runs created
    assert len(store.list_runs()) == 2
    # But chunks are deduplicated by text_hash → only 3 chunks total in DB
    chunk_total = store._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert chunk_total == 3
    # Vectors doubled (each run gets its own vector row per chunk)
    vec_total = store._conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
    assert vec_total == 6


def test_import_progress_callback(cookjohn_db: Path, store: VectorStore) -> None:
    calls: list[tuple[int, int]] = []
    import_cookjohn(
        cookjohn_path=cookjohn_db,
        zotero_path=None,
        store=store,
        progress_callback=lambda p, t: calls.append((p, t)),
    )
    assert len(calls) >= 1
    last_processed, last_total = calls[-1]
    assert last_processed == last_total == 3


def test_import_missing_db_raises(tmp_path: Path, store: VectorStore) -> None:
    from partial_recall.errors import CorpusUnavailableError

    with pytest.raises(CorpusUnavailableError):
        import_cookjohn(
            cookjohn_path=tmp_path / "nonexistent.sqlite",
            zotero_path=None,
            store=store,
        )
