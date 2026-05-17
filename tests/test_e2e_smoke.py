"""End-to-end smoke test for partial-recall v0.0.1.

Exercises the full pipeline (Zotero adapter -> PDF extract -> chunk -> embed
via real LocalONNXProvider -> store) and then verifies that semantic search
returns the expected item from the small fixture corpus.

Marked @slow because it loads the real ONNX model (~470MB, cached after
first download). On a typical M1 with the model cached, this runs in 2-5s.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from partial_recall.corpus.adapters.zotero import ZoteroAdapter
from partial_recall.embedding.providers.local_onnx import LocalONNXProvider
from partial_recall.index.pipeline import run_indexing
from partial_recall.search.orchestrator import search
from partial_recall.store.vector_store import VectorStore


@pytest.mark.slow
def test_e2e_index_then_search_finds_expected_item(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    """Full pipeline: index the Zotero fixture with real ONNX, then search for
    a query whose semantic match should be the NPLIS / Chattopadhyaya item.

    Acceptance: search returns >=1 result, and the top result's item_key is
    one of the two indexable items in the fixture.
    """
    # 1. Open the corpus adapter on the synthetic Zotero
    adapter = ZoteroAdapter(
        sqlite_path=fixtures_dir / "zotero_snapshot" / "zotero.sqlite",
        storage_path=fixtures_dir / "zotero_snapshot" / "storage",
    )

    # 2. Open a fresh vector store
    store = VectorStore(tmp_path / "vectors.sqlite")

    # 3. Real local ONNX provider (multilingual-e5-small). Cached after first run.
    provider = LocalONNXProvider(model_name="intfloat/multilingual-e5-small")

    try:
        # 4. Run the full indexing pipeline
        result = run_indexing(adapter=adapter, store=store, provider=provider)

        # 5. Assert indexing produced items + chunks + vectors
        assert result.item_count >= 2, f"expected >=2 items; got {result.item_count}"
        assert result.chunk_count >= 2, f"expected >=2 chunks; got {result.chunk_count}"
        assert result.new_vector_count >= 2, (
            f"expected >=2 vectors; got {result.new_vector_count}"
        )

        # 6. Active run is set, with the right provider metadata
        active = store.get_active_run()
        assert active is not None, "no active run after indexing"
        assert active.provider == "local-onnx"
        assert active.model_name == "intfloat/multilingual-e5-small"
        assert active.dimensions == 384
        assert active.quantization == "int8"

        # 7. Search for the NPLIS / Chattopadhyaya content (matches ITEM01XX abstract
        # and/or ITEM02XX title)
        hits = search(
            store=store,
            provider=provider,
            query="NPLIS 1986 national library policy Chattopadhyaya Committee",
            top_k=5,
        )

        # 8. At least one result
        assert len(hits) >= 1, "search returned no results"

        # 9. Top result should be from one of the two indexable items
        top = hits[0]
        assert top.item_key in {"ITEM01XX", "ITEM02XX"}, (
            f"top result has unexpected item_key {top.item_key}"
        )
        assert top.score > 0.0, f"top result has non-positive score {top.score}"
        # title should be populated from the items table
        assert top.title, "top result has empty title"
        # corpus should be 'zotero'
        assert top.corpus == "zotero"
    finally:
        adapter.close()
        provider.close()
        store.close()


@pytest.mark.slow
def test_e2e_with_cookjohn_import(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    """E2E for the cookjohn-import path: import the synthetic cookjohn fixture,
    then verify the active run is the imported one and search works.

    This is the OTHER user-path through the system - instead of indexing from
    scratch, the user runs `partial-recall import cookjohn --source ...` to
    bring in existing vectors.
    """
    from partial_recall.importers.cookjohn import import_cookjohn

    cookjohn_db = fixtures_dir / "cookjohn_snapshot" / "zotero-mcp-vectors.sqlite"
    zotero_db = fixtures_dir / "zotero_snapshot" / "zotero.sqlite"
    store = VectorStore(tmp_path / "vectors.sqlite")
    provider = LocalONNXProvider(model_name="intfloat/multilingual-e5-small")

    try:
        # Import cookjohn vectors
        result = import_cookjohn(
            cookjohn_path=cookjohn_db,
            zotero_path=zotero_db,
            store=store,
            activate=True,
        )

        # Active run should be the cookjohn-imported one
        active = store.get_active_run()
        assert active is not None
        assert active.provider == "cookjohn-imported"
        assert active.dimensions == 3072

        # NOTE: We can't easily run semantic_search here because our provider
        # is e5-small (384-dim) but the active run uses Gemini vectors (3072-dim).
        # The query vector dimension wouldn't match. In real use, the user
        # would either (a) re-index with the matching provider, or (b) keep
        # the cookjohn-imported run active and query with Gemini (v0.1.0).
        # For v0.0.1 e2e, we verify only the import path here.
        assert result.vector_count >= 3
        assert result.item_count >= 2
    finally:
        provider.close()
        store.close()
