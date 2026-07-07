"""Tests for VectorStore class."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from partial_recall.store.vector_store import VectorStore


@pytest.fixture
def store(tmp_path: Path):
    s = VectorStore(tmp_path / "vectors.sqlite")
    yield s
    s.close()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _make_int8_vector(values: list[int]) -> bytes:
    """Pack a list of int8 values into bytes."""
    return bytes((v + 256) % 256 for v in values)


def test_open_creates_db_and_runs_migrations(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "v.sqlite")
    assert (tmp_path / "v.sqlite").exists()
    store.close()


def test_create_run_returns_id(store: VectorStore) -> None:
    run_id = store.create_run(
        provider="local-onnx",
        model_name="intfloat/multilingual-e5-small",
        model_version="v1",
        dimensions=384,
        quantization="int8",
        normalized=True,
        distance_metric="cosine",
        chunker_name="recursive-char-1024-128",
        chunker_version="v1",
        started_at=_now_iso(),
    )
    assert isinstance(run_id, int)
    assert run_id > 0


def test_upsert_item_idempotent(store: VectorStore) -> None:
    store.upsert_item(
        item_key="ABC", corpus="zotero",
        item_type="journalArticle", title="Test", date="2020",
        creators_json='[]', abstract=None,
        metadata_hash="h1", last_indexed_at=_now_iso(),
        corpus_ref=None,
    )
    store.upsert_item(
        item_key="ABC", corpus="zotero",
        item_type="journalArticle", title="Test updated", date="2020",
        creators_json='[]', abstract=None,
        metadata_hash="h2", last_indexed_at=_now_iso(),
        corpus_ref=None,
    )
    rows = list(store._conn.execute("SELECT title, metadata_hash FROM items"))
    assert len(rows) == 1
    assert rows[0]["title"] == "Test updated"
    assert rows[0]["metadata_hash"] == "h2"


def test_insert_chunk_returns_id(store: VectorStore) -> None:
    store.upsert_item(
        item_key="ABC", corpus="zotero", item_type="pdf",
        title="t", date=None, creators_json='[]', abstract=None,
        metadata_hash="h", last_indexed_at=_now_iso(),
        corpus_ref=None,
    )
    chunk_id = store.insert_chunk(
        item_key="ABC", corpus="zotero",
        source_type="pdf", source_ref="pdf:p=1",
        chunk_index=0, char_offset_start=0, char_offset_end=100,
        text_hash="t1", text_preview="hello",
        chunker_version="v1", detected_locale="eng",
        indexed_at=_now_iso(),
    )
    assert chunk_id > 0


def test_chunk_exists_by_hash(store: VectorStore) -> None:
    store.upsert_item(
        item_key="ABC", corpus="zotero", item_type="pdf",
        title="t", date=None, creators_json='[]', abstract=None,
        metadata_hash="h", last_indexed_at=_now_iso(),
        corpus_ref=None,
    )
    store.insert_chunk(
        item_key="ABC", corpus="zotero",
        source_type="pdf", source_ref="pdf:p=1",
        chunk_index=0, char_offset_start=0, char_offset_end=100,
        text_hash="t1", text_preview="hello",
        chunker_version="v1", detected_locale="eng",
        indexed_at=_now_iso(),
    )
    assert store.chunk_exists(
        item_key="ABC", corpus="zotero",
        source_type="pdf", source_ref="pdf:p=1",
        chunk_index=0, chunker_version="v1", text_hash="t1",
    )
    assert not store.chunk_exists(
        item_key="ABC", corpus="zotero",
        source_type="pdf", source_ref="pdf:p=1",
        chunk_index=0, chunker_version="v1", text_hash="DIFFERENT",
    )


def test_insert_vector_and_top_k_search(store: VectorStore) -> None:
    run_id = store.create_run(
        provider="local-onnx", model_name="e5", model_version="v1",
        dimensions=4, quantization="int8", normalized=True,
        distance_metric="cosine",
        chunker_name="char-1024", chunker_version="v1",
        started_at=_now_iso(),
    )
    store.upsert_item(
        item_key="ABC", corpus="zotero", item_type="pdf",
        title="t", date=None, creators_json='[]', abstract=None,
        metadata_hash="h", last_indexed_at=_now_iso(),
        corpus_ref=None,
    )
    chunk_id = store.insert_chunk(
        item_key="ABC", corpus="zotero",
        source_type="pdf", source_ref="pdf:p=1",
        chunk_index=0, char_offset_start=0, char_offset_end=100,
        text_hash="t1", text_preview="hello",
        chunker_version="v1", detected_locale="eng",
        indexed_at=_now_iso(),
    )
    store.insert_vector(
        chunk_id=chunk_id, run_id=run_id,
        vector=_make_int8_vector([127, 0, 0, 0]),
        norm=None, indexed_at=_now_iso(),
    )
    store.activate_run(run_id)
    results = store.top_k_int8(
        run_id=run_id,
        query_vector=_make_int8_vector([127, 0, 0, 0]),
        k=5,
    )
    assert len(results) == 1
    assert results[0].chunk_id == chunk_id
    assert results[0].score > 0.99


def test_activate_run_deactivates_others(store: VectorStore) -> None:
    rid1 = store.create_run(
        provider="local-onnx", model_name="e5", model_version="v1",
        dimensions=4, quantization="int8", normalized=True,
        distance_metric="cosine", chunker_name="c", chunker_version="v1",
        started_at=_now_iso(),
    )
    rid2 = store.create_run(
        provider="local-onnx", model_name="e5", model_version="v1",
        dimensions=4, quantization="int8", normalized=True,
        distance_metric="cosine", chunker_name="c", chunker_version="v1",
        started_at=_now_iso(),
    )
    store.activate_run(rid1)
    store.activate_run(rid2)
    active = store.get_active_run()
    assert active is not None
    assert active.run_id == rid2


def test_insert_vector_if_absent_is_idempotent(store: VectorStore) -> None:
    """Extend mode must tolerate a vector committed by a
    concurrent writer between queue time and flush time."""
    run_id = store.create_run(
        provider="local-onnx", model_name="e5", model_version="v1",
        dimensions=4, quantization="int8", normalized=True,
        distance_metric="cosine", chunker_name="c", chunker_version="v1",
        started_at=_now_iso(),
    )
    store.upsert_item(
        item_key="ABC", corpus="zotero", item_type="pdf",
        title="t", date=None, creators_json='[]', abstract=None,
        metadata_hash="h", last_indexed_at=_now_iso(),
        corpus_ref=None,
    )
    chunk_id = store.insert_chunk(
        item_key="ABC", corpus="zotero",
        source_type="pdf", source_ref="pdf:p=1",
        chunk_index=0, char_offset_start=0, char_offset_end=100,
        text_hash="t1", text_preview="hello",
        chunker_version="v1", detected_locale="eng",
        indexed_at=_now_iso(),
    )
    first = store.insert_vector_if_absent(
        chunk_id=chunk_id, run_id=run_id,
        vector=_make_int8_vector([127, 0, 0, 0]),
        norm=None, indexed_at=_now_iso(),
    )
    second = store.insert_vector_if_absent(
        chunk_id=chunk_id, run_id=run_id,
        vector=_make_int8_vector([0, 127, 0, 0]),
        norm=None, indexed_at=_now_iso(),
    )
    assert first is True
    assert second is False
    rows = list(store._conn.execute(
        "SELECT COUNT(*) AS n FROM vectors WHERE chunk_id = ? AND run_id = ?",
        (chunk_id, run_id),
    ))
    assert rows[0]["n"] == 1
