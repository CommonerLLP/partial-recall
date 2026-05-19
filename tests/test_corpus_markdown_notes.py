"""Tests for MarkdownNotesAdapter (v0.3.0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from partial_recall.corpus.adapters.markdown_notes import (
    MarkdownNotesAdapter,
    _parse_frontmatter,
)
from partial_recall.corpus.types import ItemKind
from partial_recall.errors import CorpusUnavailableError

# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------


def test_parse_frontmatter_no_frontmatter() -> None:
    raw = "Just a plain note.\nNo frontmatter here."
    fm, body = _parse_frontmatter(raw)
    assert fm == {}
    assert "plain note" in body


def test_parse_frontmatter_extracts_title_and_date() -> None:
    raw = "---\ntitle: My Research Note\ndate: 2024-01-15\n---\n\nBody text here."
    fm, body = _parse_frontmatter(raw)
    assert fm["title"] == "My Research Note"
    assert fm["date"] == "2024-01-15"
    assert "Body text here" in body
    assert "title:" not in body


def test_parse_frontmatter_extracts_tag_list() -> None:
    raw = "---\ntags:\n  - caste\n  - education\n---\n\nContent."
    fm, body = _parse_frontmatter(raw)
    assert fm["tags"] == ["caste", "education"]


def test_parse_frontmatter_inline_tag_list() -> None:
    raw = "---\ntags: [caste, education, labour]\n---\n\nContent."
    fm, body = _parse_frontmatter(raw)
    assert fm["tags"] == ["caste", "education", "labour"]


def test_parse_frontmatter_empty_body() -> None:
    raw = "---\ntitle: Empty\n---\n"
    fm, body = _parse_frontmatter(raw)
    assert fm["title"] == "Empty"
    assert body.strip() == ""


# ---------------------------------------------------------------------------
# Adapter construction
# ---------------------------------------------------------------------------


def test_adapter_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(CorpusUnavailableError, match="not found"):
        MarkdownNotesAdapter(notes_path=tmp_path / "nonexistent")


def test_adapter_rejects_file_not_dir(tmp_path: Path) -> None:
    f = tmp_path / "notes.md"
    f.write_text("# hello", encoding="utf-8")
    with pytest.raises(CorpusUnavailableError, match="not a directory"):
        MarkdownNotesAdapter(notes_path=f)


def test_adapter_accepts_valid_directory(tmp_path: Path) -> None:
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    assert adapter.name == "markdown_notes"
    adapter.close()


# ---------------------------------------------------------------------------
# Walking and listing
# ---------------------------------------------------------------------------


def _make_vault(tmp_path: Path) -> Path:
    """Create a small notes folder for testing."""
    (tmp_path / "note1.md").write_text(
        "---\ntitle: First Note\ndate: 2024-01-01\n---\n\nContent of first note.",
        encoding="utf-8",
    )
    (tmp_path / "note2.md").write_text(
        "A note without frontmatter. References [[note1]].",
        encoding="utf-8",
    )
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.md").write_text("Nested note.", encoding="utf-8")
    # Should be excluded
    obsidian_dir = tmp_path / ".obsidian"
    obsidian_dir.mkdir()
    (obsidian_dir / "config.json").write_text("{}", encoding="utf-8")
    # .md in .obsidian should be excluded
    (obsidian_dir / "plugins.md").write_text("internal", encoding="utf-8")
    return tmp_path


def test_list_items_walks_md_files(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    items = list(adapter.list_items())
    titles = {i.title for i in items}
    assert len(items) == 3  # note1, note2, nested
    assert "First Note" in titles
    adapter.close()


def test_list_items_excludes_obsidian_dir(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    items = list(adapter.list_items())
    refs = [i.corpus_ref or "" for i in items]
    assert not any(".obsidian" in r for r in refs)
    adapter.close()


def test_list_items_corpus_is_markdown_notes(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    items = list(adapter.list_items())
    assert all(i.corpus == "markdown_notes" for i in items)
    adapter.close()


def test_item_key_is_stable(tmp_path: Path) -> None:
    (tmp_path / "stable.md").write_text("content", encoding="utf-8")
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    items1 = list(adapter.list_items())
    items2 = list(adapter.list_items())
    assert items1[0].item_key == items2[0].item_key
    adapter.close()


def test_count_items_matches_list(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    assert adapter.count_items() == len(list(adapter.list_items()))
    adapter.close()


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def test_get_text_strips_frontmatter(tmp_path: Path) -> None:
    note = tmp_path / "research.md"
    note.write_text(
        "---\ntitle: Research\ndate: 2024-01-01\n---\n\nThis is the body.",
        encoding="utf-8",
    )
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    items = list(adapter.list_items())
    sources = list(adapter.get_sources(items[0]))
    text = adapter.get_text(items[0], sources[0])
    assert text is not None
    assert "This is the body" in text
    assert "title:" not in text
    assert "date:" not in text
    adapter.close()


def test_get_text_preserves_wikilinks(tmp_path: Path) -> None:
    note = tmp_path / "linked.md"
    note.write_text("See [[other note]] for details.", encoding="utf-8")
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    items = list(adapter.list_items())
    sources = list(adapter.get_sources(items[0]))
    text = adapter.get_text(items[0], sources[0])
    assert "[[other note]]" in text
    adapter.close()


def test_get_text_returns_none_for_missing_file(tmp_path: Path) -> None:
    note = tmp_path / "gone.md"
    note.write_text("content", encoding="utf-8")
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    items = list(adapter.list_items())
    sources = list(adapter.get_sources(items[0]))
    note.unlink()  # delete after listing
    text = adapter.get_text(items[0], sources[0])
    assert text is None
    adapter.close()


# ---------------------------------------------------------------------------
# Ignorefile
# ---------------------------------------------------------------------------


def test_ignorefile_excludes_matching_notes(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("keep this", encoding="utf-8")
    (tmp_path / "draft.md").write_text("skip this", encoding="utf-8")
    (tmp_path / ".partial-recallignore").write_text("draft.md\n", encoding="utf-8")
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    items = list(adapter.list_items())
    titles = {i.title for i in items}
    assert "keep" in titles
    assert "draft" not in titles
    adapter.close()


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def test_get_sources_yields_note_source(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    adapter = MarkdownNotesAdapter(notes_path=tmp_path)
    items = list(adapter.list_items())
    sources = list(adapter.get_sources(items[0]))
    assert len(sources) == 1
    assert sources[0].source_type == "note"
    assert sources[0].kind == ItemKind.NOTE
    adapter.close()
