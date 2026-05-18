"""Tests for FolderAdapter (v0.2.0 B3)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from partial_recall.corpus.adapters.folder import FolderAdapter, _stable_item_key
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
    # Delete underneath us, then retry get_text.
    Path(source.source_ref).unlink()
    assert adapter.get_text(item, source) is None


def test_metadata_hash_stable_per_run(adapter: FolderAdapter) -> None:
    first = {item.item_key: item.metadata_hash for item in adapter.list_items()}
    second = {item.item_key: item.metadata_hash for item in adapter.list_items()}
    assert first == second
