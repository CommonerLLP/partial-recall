"""Recursive character chunker.

Targets 1024 chars per chunk with 128 chars overlap. Prefers to split at
paragraph (\\n\\n), then sentence (. ! ?), then whitespace, then any char.

Deterministic and idempotent: same input always produces same chunks.
"""

from __future__ import annotations

from dataclasses import dataclass

CHUNKER_VERSION = "recursive-char-1024-128-v1"

CHUNK_SIZE = 1024
CHUNK_OVERLAP = 128
MIN_CHUNK_SIZE = 100
MAX_CHUNK_SIZE = 1200  # soft cap; we may overshoot slightly to hit a natural boundary

# Boundary preferences, most-preferred first.
_BOUNDARIES: tuple[str, ...] = (
    "\n\n",       # paragraph
    ". ",         # sentence
    "! ",
    "? ",
    "\n",
    " ",          # any whitespace
    "",           # fallback: split anywhere
)


@dataclass(frozen=True)
class Chunk:
    text: str
    chunk_index: int
    char_offset_start: int
    char_offset_end: int


def chunk_text(text: str) -> list[Chunk]:
    """Split text into overlapping chunks at natural boundaries.

    Returns an empty list for empty input. Single chunk if input fits in one.
    """
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [Chunk(text=text, chunk_index=0, char_offset_start=0, char_offset_end=len(text))]

    chunks: list[Chunk] = []
    pos = 0
    idx = 0
    n = len(text)

    while pos < n:
        # Tentative end at CHUNK_SIZE
        target_end = pos + CHUNK_SIZE
        if target_end >= n:
            # Final chunk: take the remainder
            chunk_str = text[pos:n]
            chunks.append(Chunk(
                text=chunk_str,
                chunk_index=idx,
                char_offset_start=pos,
                char_offset_end=n,
            ))
            break

        # Find the best boundary in [pos + MIN_CHUNK_SIZE, target_end + buffer]
        best_end = _find_boundary(text, pos, target_end)
        chunk_str = text[pos:best_end]
        chunks.append(Chunk(
            text=chunk_str,
            chunk_index=idx,
            char_offset_start=pos,
            char_offset_end=best_end,
        ))
        idx += 1

        # Advance with overlap
        next_pos = best_end - CHUNK_OVERLAP
        if next_pos <= pos:
            # No progress would be made; force advance
            next_pos = best_end
        pos = next_pos

    # Merge tiny final chunk into the previous one if applicable
    if len(chunks) >= 2 and len(chunks[-1].text) < MIN_CHUNK_SIZE:
        last = chunks.pop()
        second_last = chunks.pop()
        # New chunk spans second_last.start through last.end
        merged_text = text[second_last.char_offset_start:last.char_offset_end]
        chunks.append(Chunk(
            text=merged_text,
            chunk_index=second_last.chunk_index,
            char_offset_start=second_last.char_offset_start,
            char_offset_end=last.char_offset_end,
        ))

    return chunks


def _find_boundary(text: str, start: int, target_end: int) -> int:
    """Find the best place to split, preferring paragraph > sentence > whitespace > anywhere.

    Searches backwards from target_end within a soft window.
    Returns the index where the chunk should END (exclusive).
    """
    n = len(text)
    min_end = start + MIN_CHUNK_SIZE
    max_end = min(start + MAX_CHUNK_SIZE, n)
    # Clamp target_end into the [min_end, max_end] range
    search_end = min(target_end, max_end)
    search_start = max(min_end, start + 1)

    for boundary in _BOUNDARIES:
        if boundary == "":
            # Fallback: split at target_end exactly
            return search_end
        # Search backwards from search_end for the boundary
        idx = text.rfind(boundary, search_start, search_end)
        if idx != -1:
            # Split right AFTER the boundary
            return idx + len(boundary)
    # Should be unreachable due to "" fallback
    return search_end
