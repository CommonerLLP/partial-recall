"""Tests for corpus types."""

from __future__ import annotations

import dataclasses

import pytest

from partial_recall.corpus.types import Item, ItemKind, Source


def test_itemkind_values() -> None:
    assert ItemKind.TEXT.value == "text"
    assert ItemKind.NOTE.value == "note"
    assert ItemKind.ANNOTATION.value == "annotation"
    assert ItemKind.METADATA.value == "metadata"


def test_item_construction() -> None:
    item = Item(
        item_key="ABC123", corpus="zotero",
        item_type="journalArticle", title="A paper",
        date="2020-01", creators=[{"first": "A", "last": "B"}],
        abstract="An abstract", metadata_hash="h1",
    )
    assert item.item_key == "ABC123"


def test_source_construction() -> None:
    src = Source(source_type="pdf", source_ref="pdf:p=12", kind=ItemKind.TEXT)
    assert src.kind == ItemKind.TEXT


def test_item_is_frozen() -> None:
    item = Item(
        item_key="x", corpus="zotero", item_type="t",
        title=None, date=None, creators=[], abstract=None, metadata_hash="h",
    )
    assert dataclasses.is_dataclass(item)
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.item_key = "y"  # type: ignore[misc]
