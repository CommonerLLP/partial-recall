"""Tests for the MCP semantic_status tool (v0.2.3 C1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.index.pipeline import run_indexing
from partial_recall.mcp.compat import tool_input_schema
from partial_recall.mcp.tools.semantic_status import (
    SEMANTIC_STATUS_TOOL,
    handle_semantic_status,
)
from partial_recall.store.vector_store import VectorStore
from tests.test_pipeline import FakeEmbeddingProvider


@pytest.fixture
def indexed_store(tmp_path: Path, fixtures_dir: Path):
    adapter = ZoteroAdapter(
        sqlite_path=fixtures_dir / "zotero_snapshot" / "zotero.sqlite",
        storage_path=fixtures_dir / "zotero_snapshot" / "storage",
    )
    store = VectorStore(tmp_path / "vectors.sqlite")
    provider = FakeEmbeddingProvider()
    run_indexing(adapter=adapter, store=store, provider=provider)
    yield store
    adapter.close()
    store.close()


def test_tool_schema_takes_no_arguments() -> None:
    schema = tool_input_schema(SEMANTIC_STATUS_TOOL)
    assert schema["type"] == "object"
    assert schema.get("properties", {}) == {}
    # No `required` fields, and additionalProperties is locked down.
    assert schema.get("additionalProperties") is False


@pytest.mark.asyncio
async def test_status_reports_totals_after_indexing(indexed_store) -> None:
    result = await handle_semantic_status({}, store=indexed_store)
    assert len(result) == 1
    payload = json.loads(result[0].text)
    # Schema version is the one from the migration that was applied.
    assert payload["schema_version"] >= 1
    assert payload["totals"]["items"] >= 1
    assert payload["totals"]["chunks"] >= 1
    assert payload["totals"]["vectors"] >= 1
    # The fixture corpus is the zotero snapshot.
    assert "zotero" in payload["corpora"]
    assert payload["corpora"]["zotero"] == payload["totals"]["items"]


@pytest.mark.asyncio
async def test_status_reports_active_run_metadata(indexed_store) -> None:
    payload = json.loads(
        (await handle_semantic_status({}, store=indexed_store))[0].text
    )
    active = payload["embedding_runs"]["active"]
    assert active is not None
    assert "provider" in active
    assert "model_name" in active
    assert "dimensions" in active
    assert "quantization" in active
    assert payload["embedding_runs"]["count"] >= 1


@pytest.mark.asyncio
async def test_status_handles_empty_store(tmp_path: Path) -> None:
    """A brand-new store with no runs is a legitimate state — status
    should report zero counts and active=None, not crash."""
    store = VectorStore(tmp_path / "empty.sqlite")
    try:
        payload = json.loads(
            (await handle_semantic_status({}, store=store))[0].text
        )
    finally:
        store.close()
    assert payload["totals"] == {"items": 0, "chunks": 0, "vectors": 0}
    assert payload["corpora"] == {}
    assert payload["embedding_runs"]["count"] == 0
    assert payload["embedding_runs"]["active"] is None
