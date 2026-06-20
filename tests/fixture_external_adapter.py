"""Fixture CorpusAdapter loaded through a dotted import path in tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from partial_recall.corpus.types import Item, ItemKind, Source


class FixtureExternalAdapter:
    """Tiny external-looking adapter for registry tests."""

    name = "fixture_external"
    version = "1"
    capabilities = frozenset({ItemKind.TEXT, ItemKind.METADATA})

    def count_items(self, since: datetime | None = None) -> int | None:
        return 1

    def list_items(self, since: datetime | None = None) -> Iterator[Item]:
        yield Item(
            item_key="fixture-1",
            corpus=self.name,
            item_type="document",
            title="Fixture External Item",
            date=None,
            creators=[],
            abstract=None,
            metadata_hash="fixture-hash",
        )

    def get_sources(self, item: Item) -> Iterator[Source]:
        yield Source(
            source_type="text",
            source_ref="fixture://external/1",
            kind=ItemKind.TEXT,
        )

    def get_text(self, item: Item, source: Source) -> str | None:
        return "fixture external adapter text"

    def get_image(self, item: Item, source: Source) -> bytes | None:
        return None

    def close(self) -> None:
        return None
