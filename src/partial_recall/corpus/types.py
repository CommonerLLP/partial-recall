"""Data types for the corpus adapter interface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ItemKind(StrEnum):
    TEXT = "text"
    NOTE = "note"
    ANNOTATION = "annotation"
    METADATA = "metadata"
    IMAGE = "image"   # v0.3.0+
    MIXED = "mixed"   # IIIF, v0.4.0+


@dataclass(frozen=True)
class Item:
    item_key: str
    corpus: str
    item_type: str
    title: str | None
    date: str | None
    creators: list[dict[str, str]]
    abstract: str | None
    metadata_hash: str
    corpus_ref: str | None = None
    # Library-location fields (Zotero richness, v0.2.4). Tell a
    # reader where a physical / catalogued copy lives.
    archive: str | None = None
    archive_location: str | None = None
    call_number: str | None = None
    library_catalog: str | None = None


@dataclass(frozen=True)
class Source:
    source_type: str
    source_ref: str | None
    kind: ItemKind
