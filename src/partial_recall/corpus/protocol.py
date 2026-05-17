"""CorpusAdapter Protocol."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Protocol, runtime_checkable

from partial_recall.corpus.types import Item, ItemKind, Source


@runtime_checkable
class CorpusAdapter(Protocol):
    """Pluggable source of indexable items.

    v0.0.1: ZoteroAdapter only.
    v0.1.0: + FolderAdapter.
    """

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def capabilities(self) -> set[ItemKind]: ...

    def list_items(self, since: datetime | None = None) -> Iterator[Item]: ...

    def get_sources(self, item: Item) -> Iterator[Source]: ...

    def get_text(self, item: Item, source: Source) -> str | None: ...

    def get_image(self, item: Item, source: Source) -> bytes | None: ...

    def close(self) -> None: ...
