"""Tests for the MCP place_item tool (discovery positioning)."""

from __future__ import annotations

import json
import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

from partial_recall.embedding.types import EmbeddingBatch
from partial_recall.mcp.tools.place_item import PLACE_ITEM_TOOL, handle_place_item
from partial_recall.store.vector_store import VectorStore


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _vec(values: list[int]) -> bytes:
    return struct.pack(f"{len(values)}b", *values)


class FixedVecProvider:
    """Returns one fixed int8 vector for every query — deterministic scoring."""

    def __init__(self, vector: list[int]) -> None:
        self._vector = _vec(vector)

    def embed(
        self,
        texts: list[str],
        task: str = "search_document",
        batch_size: int | None = None,
    ) -> EmbeddingBatch:
        return EmbeddingBatch(texts=texts, vectors=[self._vector] * len(texts), norms=None)

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


@pytest.fixture
def store_with_two_items(tmp_path: Path):
    """Two indexed items: A is identical to the [127,0,0,0] query direction,
    B is close-but-lower. Lets us assert ordering, owned, and density."""
    store = VectorStore(tmp_path / "vectors.sqlite")
    run_id = store.create_run(
        provider="fake", model_name="fake-model", model_version="v1",
        dimensions=4, quantization="int8", normalized=True,
        distance_metric="cosine", chunker_name="char", chunker_version="v1",
        started_at=_now(),
    )
    store.activate_run(run_id)

    items = [
        ("A", "Government as Practice", [127, 0, 0, 0]),
        ("B", "Land and Everyday Politics", [110, 60, 0, 0]),
    ]
    for key, title, vec in items:
        store.upsert_item(
            item_key=key, corpus="zotero", item_type="book", title=title,
            date=None, creators_json="[]", abstract=None, metadata_hash=f"h{key}",
            last_indexed_at=_now(), corpus_ref=None,
        )
        cid = store.insert_chunk(
            item_key=key, corpus="zotero", source_type="abstract", source_ref=None,
            chunk_index=0, char_offset_start=0, char_offset_end=10,
            text_hash=f"t{key}", text_preview=f"preview {key}",
            chunker_version="v1", detected_locale=None, indexed_at=_now(),
        )
        store.insert_vector(
            chunk_id=cid, run_id=run_id, vector=_vec(vec), norm=None, indexed_at=_now(),
        )
    yield store
    store.close()


def test_tool_schema_requires_title() -> None:
    schema = PLACE_ITEM_TOOL.inputSchema
    assert "title" in schema["properties"]
    assert "title" in schema.get("required", [])


@pytest.mark.asyncio
async def test_missing_title_returns_error(store_with_two_items: VectorStore) -> None:
    result = await handle_place_item(
        arguments={}, store=store_with_two_items, provider=FixedVecProvider([127, 0, 0, 0]),
    )
    parsed = json.loads(result[0].text)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_positions_against_corpus_and_flags_owned(store_with_two_items: VectorStore) -> None:
    # Query direction identical to item A's vector → score ~1.0 → likely_owned.
    result = await handle_place_item(
        arguments={"title": "Government as Practice", "top_k": 5},
        store=store_with_two_items, provider=FixedVecProvider([127, 0, 0, 0]),
    )
    parsed = json.loads(result[0].text)
    assert parsed["neighbours"], "expected at least one neighbour"
    assert parsed["neighbours"][0]["item_key"] == "A"
    assert parsed["placement"]["likely_owned"] is True
    assert parsed["placement"]["owned_match"]["item_key"] == "A"
    # Active run surfaced so the consumer knows the embedding space.
    assert parsed["interpretation"]["embedding_model"] == "fake-model"


@pytest.mark.asyncio
async def test_gap_is_thin_and_not_owned(store_with_two_items: VectorStore) -> None:
    # Query orthogonal to every stored vector (all in dim 0/1) → low scores.
    result = await handle_place_item(
        arguments={"title": "Quantum Field Theory"},
        store=store_with_two_items, provider=FixedVecProvider([0, 0, 127, 0]),
    )
    parsed = json.loads(result[0].text)
    assert parsed["placement"]["likely_owned"] is False
    assert parsed["placement"]["density"] in {"thin", "empty"}


@pytest.mark.asyncio
async def test_no_index_returns_error_payload(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / "empty.sqlite")
    result = await handle_place_item(
        arguments={"title": "anything"},
        store=store, provider=FixedVecProvider([127, 0, 0, 0]),
    )
    parsed = json.loads(result[0].text)
    assert "error" in parsed
    store.close()
