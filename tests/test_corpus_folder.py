"""Tests for FolderAdapter (v0.2.0 B3)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.corpus.adapters._shared import stable_item_key as _stable_item_key
from partial_recall.corpus.adapters.folder import FolderAdapter
from partial_recall.corpus.types import ItemKind, Source
from partial_recall.errors import CorpusUnavailableError


def _seed(root: Path) -> None:
    """Populate a small heterogeneous corpus."""
    (root / "notes").mkdir()
    (root / ".obsidian").mkdir()  # dotdir, must be excluded by default
    (root / "drafts").mkdir()

    (root / "notes" / "caste.md").write_text(
        "# Notes on caste\n\nThis is a markdown note.", encoding="utf-8"
    )
    (root / "notes" / "scratch.txt").write_text(
        "Free-form text notes.\n", encoding="utf-8"
    )
    (root / "drafts" / "chapter1.md").write_text(
        "## Chapter 1\n\nFirst draft.", encoding="utf-8"
    )
    (root / "notes" / "sketch.markdown").write_text(
        "alt markdown extension", encoding="utf-8"
    )
    (root / ".obsidian" / "config").write_text("tooling", encoding="utf-8")
    # Unsupported file type — should be skipped.
    (root / "notes" / "image.png").write_bytes(b"\x89PNG-fake")
    # Deferred extensions — known but no extractor yet.
    (root / "drafts" / "book.epub").write_bytes(b"PK-fake-epub")
    # Hidden file — must be skipped.
    (root / ".secret.md").write_text("hidden", encoding="utf-8")


@pytest.fixture
def corpus_root(tmp_path: Path) -> Iterator[Path]:
    _seed(tmp_path)
    return tmp_path


@pytest.fixture
def adapter(corpus_root: Path) -> Iterator[FolderAdapter]:
    a = FolderAdapter(roots=[corpus_root])
    yield a
    a.close()


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------


def test_stable_item_key_is_deterministic(tmp_path: Path) -> None:
    p = tmp_path / "alpha.md"
    p.write_text("x", encoding="utf-8")
    assert _stable_item_key(p) == _stable_item_key(p)


def test_stable_item_key_differs_per_path(tmp_path: Path) -> None:
    a = tmp_path / "alpha.md"
    b = tmp_path / "beta.md"
    a.write_text("x", encoding="utf-8")
    b.write_text("x", encoding="utf-8")
    assert _stable_item_key(a) != _stable_item_key(b)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_adapter_rejects_empty_roots() -> None:
    with pytest.raises(CorpusUnavailableError, match="at least one"):
        FolderAdapter(roots=[])


def test_adapter_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(CorpusUnavailableError, match="not found"):
        FolderAdapter(roots=[tmp_path / "nope"])


def test_adapter_rejects_non_directory(tmp_path: Path) -> None:
    p = tmp_path / "file.md"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(CorpusUnavailableError, match="not a directory"):
        FolderAdapter(roots=[p])


# ---------------------------------------------------------------------------
# Walking and filtering
# ---------------------------------------------------------------------------


def test_walk_yields_supported_extensions(adapter: FolderAdapter) -> None:
    keys = [item.item_key for item in adapter.list_items()]
    titles = sorted(item.title for item in adapter.list_items())
    assert "caste" in titles
    assert "chapter1" in titles
    assert "scratch" in titles
    assert "sketch" in titles
    # image.png is unsupported — skipped.
    assert "image" not in titles
    # epub is deferred (in extension list but no extractor) — currently
    # NOT in default extensions so it's filtered at walk stage.
    assert "book" not in titles
    # Hidden files / dotdirs excluded.
    assert ".secret" not in titles
    assert "config" not in titles
    assert len(keys) == len(set(keys)), "item keys must be unique"


def test_count_items_matches_list(adapter: FolderAdapter) -> None:
    count = adapter.count_items()
    listed = list(adapter.list_items())
    assert count == len(listed)


def test_non_recursive_only_walks_top_level(corpus_root: Path) -> None:
    # Put one md at top level, then count.
    (corpus_root / "top.md").write_text("top-level note", encoding="utf-8")
    flat = FolderAdapter(roots=[corpus_root], recursive=False)
    try:
        titles = sorted(item.title for item in flat.list_items())
        assert "top" in titles
        assert "caste" not in titles  # in notes/, not visible non-recursively
    finally:
        flat.close()


def test_partial_recallignore_excludes_globs(corpus_root: Path) -> None:
    (corpus_root / ".partial-recallignore").write_text(
        "# ignore drafts entirely\n"
        "drafts/\n"
        "# also a single named file\n"
        "notes/scratch.txt\n",
        encoding="utf-8",
    )
    a = FolderAdapter(roots=[corpus_root])
    try:
        titles = sorted(item.title for item in a.list_items())
        assert "caste" in titles
        assert "sketch" in titles
        assert "chapter1" not in titles  # under drafts/ → ignored
        assert "scratch" not in titles  # explicit file ignore
    finally:
        a.close()


def test_explicit_extension_filter(corpus_root: Path) -> None:
    a = FolderAdapter(roots=[corpus_root], extensions=frozenset({".txt"}))
    try:
        titles = sorted(item.title for item in a.list_items())
        assert titles == ["scratch"]
    finally:
        a.close()


# ---------------------------------------------------------------------------
# Text extraction round-trip
# ---------------------------------------------------------------------------


def test_get_text_returns_markdown_body(adapter: FolderAdapter) -> None:
    item = next(i for i in adapter.list_items() if i.title == "caste")
    source = next(adapter.get_sources(item))
    text = adapter.get_text(item, source)
    assert text is not None
    assert "Notes on caste" in text
    assert "markdown note" in text


def test_get_text_returns_plain_text(adapter: FolderAdapter) -> None:
    item = next(i for i in adapter.list_items() if i.title == "scratch")
    source = next(adapter.get_sources(item))
    text = adapter.get_text(item, source)
    assert text is not None
    assert "Free-form text" in text


def test_get_text_returns_none_for_deferred_extension(
    corpus_root: Path,
) -> None:
    # Force-include .epub so we exercise the deferred branch of get_text.
    a = FolderAdapter(
        roots=[corpus_root],
        extensions=frozenset({".md", ".epub"}),
    )
    try:
        epub_item = next(
            i for i in a.list_items() if i.title == "book"
        )
        source = next(a.get_sources(epub_item))
        assert a.get_text(epub_item, source) is None
    finally:
        a.close()


def test_get_text_returns_none_for_missing_file(
    corpus_root: Path, adapter: FolderAdapter
) -> None:
    item = next(i for i in adapter.list_items() if i.title == "caste")
    source = next(adapter.get_sources(item))
    # source_ref is now "{root_idx}:{rel_posix}" — strip the prefix before resolving.
    _, _, rel = source.source_ref.partition(":")
    (corpus_root / rel).unlink()
    assert adapter.get_text(item, source) is None


def test_metadata_hash_stable_per_run(adapter: FolderAdapter) -> None:
    first = {item.item_key: item.metadata_hash for item in adapter.list_items()}
    second = {item.item_key: item.metadata_hash for item in adapter.list_items()}
    assert first == second


def test_source_ref_is_relative(adapter: FolderAdapter) -> None:
    """source_ref must be a POSIX-relative path, not an absolute path.

    Absolute paths are machine-specific and break portable/collaborative
    indices when the folder moves or the repo is cloned elsewhere (issue #23).
    """
    for item in adapter.list_items():
        for source in adapter.get_sources(item):
            assert not Path(source.source_ref).is_absolute(), (
                f"source_ref should be relative, got: {source.source_ref!r}"
            )


def test_get_text_works_with_absolute_legacy_source_ref(
    corpus_root: Path, adapter: FolderAdapter
) -> None:
    """get_text must still work when source_ref is an absolute path.

    Rows indexed before fix #23 carry absolute paths in the DB. The
    adapter must handle them as a backwards-compatible fallback.
    """
    item = next(i for i in adapter.list_items() if i.title == "caste")
    abs_source = item.corpus_ref  # absolute path, as stored in old DB rows
    legacy_source = Source(
        source_type="file",
        source_ref=abs_source,
        kind=ItemKind.TEXT,
    )
    text = adapter.get_text(item, legacy_source)
    assert text is not None
    assert "caste" in text.lower()


# ---------------------------------------------------------------------------
# Stable root ids + source_ref migration
# ---------------------------------------------------------------------------


def _two_roots(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "root_a"
    b = tmp_path / "root_b"
    for root in (a, b):
        root.mkdir(parents=True)
    (a / "alpha.md").write_text("alpha text", encoding="utf-8")
    (b / "bravo.md").write_text("bravo text", encoding="utf-8")
    return a, b


def _refs(adapter: FolderAdapter) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in adapter.list_items():
        for source in adapter.get_sources(item):
            out[item.title] = source.source_ref
    return out


def test_source_refs_survive_root_reordering(tmp_path: Path) -> None:
    """THE bug: source_ref used to embed the root's position in config,
    so reordering roots orphaned every chunk and re-embedded the corpus."""
    a, b = _two_roots(tmp_path)
    first = FolderAdapter(roots=[a, b])
    second = FolderAdapter(roots=[b, a])
    try:
        assert _refs(first) == _refs(second)
    finally:
        first.close()
        second.close()


def test_resolves_every_source_ref_format(tmp_path: Path) -> None:
    a, b = _two_roots(tmp_path)
    adapter = FolderAdapter(roots=[a, b])
    try:
        stable = _refs(adapter)["alpha"]
        expected = (a / "alpha.md").resolve()
        assert adapter._resolve_source_ref(stable) == expected
        # Legacy positional format still resolves through root order.
        assert adapter._resolve_source_ref("0:alpha.md") == expected
        # Legacy absolute path.
        assert adapter._resolve_source_ref(str(expected)) == expected
        # Bare relative fallback.
        assert adapter._resolve_source_ref("alpha.md") == expected
    finally:
        adapter.close()


def test_migrate_source_refs_rewrites_and_merges(tmp_path: Path) -> None:
    """Legacy rows (positional prefix + absolute path) are rewritten in
    place; a legacy row whose target identity already exists is merged
    with its vectors preserved on the survivor."""
    from datetime import UTC, datetime

    from partial_recall.store.vector_store import VectorStore

    a, b = _two_roots(tmp_path / "corpus")
    adapter = FolderAdapter(roots=[a, b])
    store = VectorStore(tmp_path / "vectors.sqlite")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    run_id = store.create_run(
        provider="fake", model_name="fake", model_version="v1",
        dimensions=4, quantization="int8", normalized=True,
        distance_metric="cosine", chunker_name="c", chunker_version="v1",
        started_at=now,
    )
    try:
        alpha_key = _stable_item_key(a / "alpha.md")
        bravo_key = _stable_item_key(b / "bravo.md")
        for key in (alpha_key, bravo_key):
            store.upsert_item(
                item_key=key, corpus="folder", item_type="file", title=key,
                date=None, creators_json="[]", abstract=None,
                metadata_hash=f"h-{key}", last_indexed_at=now, corpus_ref=None,
            )
        # Legacy positional row (no stable twin) — should be rewritten.
        store.insert_chunk(
            item_key=alpha_key, corpus="folder", source_type="file",
            source_ref="0:alpha.md", chunk_index=0,
            char_offset_start=0, char_offset_end=10, text_hash="t1",
            text_preview="alpha text", chunker_version="v1", indexed_at=now,
            detected_locale=None,
        )
        # Drift pair: a stable-format row (with the active vector) AND a
        # legacy absolute-path row (with an older run's vector) for the
        # same chunk — should merge, keeping both vectors.
        stable_ref = _refs(adapter)["bravo"]
        stable_row = store.insert_chunk(
            item_key=bravo_key, corpus="folder", source_type="file",
            source_ref=stable_ref, chunk_index=0,
            char_offset_start=0, char_offset_end=10, text_hash="t2",
            text_preview="bravo text", chunker_version="v1", indexed_at=now,
            detected_locale=None,
        )
        legacy_abs = store.insert_chunk(
            item_key=bravo_key, corpus="folder", source_type="file",
            source_ref=str((b / "bravo.md").resolve()), chunk_index=0,
            char_offset_start=0, char_offset_end=10, text_hash="t2",
            text_preview="bravo text", chunker_version="v1", indexed_at=now,
            detected_locale=None,
        )
        old_run = store.create_run(
            provider="fake", model_name="fake", model_version="v1",
            dimensions=4, quantization="int8", normalized=True,
            distance_metric="cosine", chunker_name="c", chunker_version="v1",
            started_at=now,
        )
        store.insert_vector(
            chunk_id=stable_row, run_id=run_id,
            vector=b"\x7f\x00\x00\x00", norm=None, indexed_at=now,
        )
        store.insert_vector(
            chunk_id=legacy_abs, run_id=old_run,
            vector=b"\x00\x7f\x00\x00", norm=None, indexed_at=now,
        )
        # Unmappable row: absolute path outside every root — left alone.
        outside = tmp_path / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        outside_key = _stable_item_key(outside)
        store.upsert_item(
            item_key=outside_key, corpus="folder", item_type="file",
            title="outside", date=None, creators_json="[]", abstract=None,
            metadata_hash="h-out", last_indexed_at=now, corpus_ref=None,
        )
        store.insert_chunk(
            item_key=outside_key, corpus="folder", source_type="file",
            source_ref=str(outside.resolve()), chunk_index=0,
            char_offset_start=0, char_offset_end=7, text_hash="t3",
            text_preview="outside", chunker_version="v1", indexed_at=now,
            detected_locale=None,
        )

        counts = adapter.migrate_source_refs(store)

        assert counts == {"rewritten": 1, "merged": 1, "skipped": 1}
        refs = {
            r["source_ref"]
            for r in store.iter_chunk_refs(corpus="folder")
        }
        assert _refs(adapter)["alpha"] in refs          # positional → stable
        assert "0:alpha.md" not in refs
        assert str((b / "bravo.md").resolve()) not in refs   # merged away
        assert str(outside.resolve()) in refs           # skipped, untouched
        # Both vectors survive on the surviving bravo row.
        rows = store._conn.execute(
            "SELECT run_id FROM vectors WHERE chunk_id = ? ORDER BY run_id",
            (stable_row,),
        ).fetchall()
        assert [r["run_id"] for r in rows] == [run_id, old_run]
        # Idempotent: second run is a no-op.
        assert adapter.migrate_source_refs(store) == {
            "rewritten": 0, "merged": 0, "skipped": 1,
        }
    finally:
        adapter.close()
        store.close()


def test_reordered_roots_do_not_reembed(tmp_path: Path) -> None:
    """End-to-end regression for the root-order footgun: index with roots
    [A, B], reorder to [B, A], extend — nothing may be re-created or
    re-embedded."""
    from partial_recall.index.pipeline import run_indexing
    from partial_recall.store.vector_store import VectorStore
    from tests.test_pipeline import FakeEmbeddingProvider

    a, b = _two_roots(tmp_path / "corpus")
    store = VectorStore(tmp_path / "vectors.sqlite")
    first_adapter = FolderAdapter(roots=[a, b])
    second_adapter = FolderAdapter(roots=[b, a])
    try:
        first = run_indexing(
            adapter=first_adapter, store=store, provider=FakeEmbeddingProvider(),
        )
        assert first.chunk_count == 2
        result = run_indexing(
            adapter=second_adapter, store=store,
            provider=FakeEmbeddingProvider(),
            extend_run_id=first.run_id,
        )
        assert result.chunk_count == 0
        assert result.new_vector_count == 0
        assert result.skipped_chunk_count == 2
    finally:
        first_adapter.close()
        second_adapter.close()
        store.close()
