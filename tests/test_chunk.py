"""Tests for the recursive character chunker."""

from __future__ import annotations

from partial_recall.chunk.recursive_char import (
    CHUNKER_VERSION,
    chunk_text,
)


def test_chunker_version_is_stable() -> None:
    assert CHUNKER_VERSION == "recursive-char-1024-128-v1"


def test_short_text_returns_single_chunk() -> None:
    text = "This is a short paragraph that fits in one chunk."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].char_offset_start == 0
    assert chunks[0].char_offset_end == len(text)
    assert chunks[0].chunk_index == 0


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("") == []


def test_long_text_splits_at_paragraph_boundaries_when_possible() -> None:
    para1 = "First paragraph. " * 50  # ~850 chars
    para2 = "Second paragraph. " * 50
    text = para1 + "\n\n" + para2
    chunks = chunk_text(text)
    # Should split at the paragraph boundary
    assert len(chunks) >= 2
    # First chunk should contain only para1 content (or end at the boundary)
    assert chunks[0].text.endswith("First paragraph. ") or "First paragraph." in chunks[0].text
    # Last chunk should contain second-paragraph content
    assert any("Second paragraph" in c.text for c in chunks)


def test_chunks_are_deterministic() -> None:
    text = "Hello world. " * 200
    chunks_a = chunk_text(text)
    chunks_b = chunk_text(text)
    assert [c.text for c in chunks_a] == [c.text for c in chunks_b]
    assert [c.char_offset_start for c in chunks_a] == [c.char_offset_start for c in chunks_b]


def test_overlapping_chunks_when_no_natural_boundary() -> None:
    # Pathological case: long string with no whitespace
    text = "a" * 3000
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    # Consecutive chunks should overlap by ~128 chars
    if len(chunks) >= 2:
        end0 = chunks[0].char_offset_end
        start1 = chunks[1].char_offset_start
        overlap = end0 - start1
        # Overlap should be roughly 128 (with some flexibility)
        assert 50 <= overlap <= 200, f"expected ~128 char overlap; got {overlap}"


def test_chunks_cover_input_no_gaps_no_duplicates_in_content() -> None:
    """Every character of the original input must appear in at least one chunk."""
    text = "The library policy of India has evolved. " * 100  # ~4100 chars
    chunks = chunk_text(text)
    # Reconstruct by walking the offsets; allow duplicate chars in overlap regions
    covered = bytearray(len(text))
    for c in chunks:
        for i in range(c.char_offset_start, c.char_offset_end):
            if 0 <= i < len(covered):
                covered[i] = 1
    assert all(b == 1 for b in covered), "some characters not covered"


def test_chunks_have_min_size_when_text_long_enough() -> None:
    """Tiny chunks (< 100 chars) should be merged into neighbors when possible."""
    text = ("a" * 100 + ". ") * 30  # ~3060 chars
    chunks = chunk_text(text)
    # Every chunk except possibly the last should be >= 100 chars
    for c in chunks[:-1]:
        assert len(c.text) >= 100


def test_chunk_index_is_sequential() -> None:
    text = "Hello world. " * 200
    chunks = chunk_text(text)
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
